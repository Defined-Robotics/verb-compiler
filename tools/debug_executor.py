#!/usr/bin/env python3
"""Debug BT XML executor — walks a compiled BT XML and sends Nav2 goals.

WARNING: This is a debug/integration-test tool, NOT the production runtime.
The production runtime uses BT.CPP in C++ (defined_runtime).

Usage:
    python3 debug_executor.py <bt_xml_file> [--dry-run] [--verify-odom]

Exit codes:
    0 — all actions succeeded
    1 — one or more actions failed
"""

from __future__ import annotations

import argparse
import sys
import time
import xml.etree.ElementTree as ET


def parse_bt_xml(path: str) -> list[dict]:
    """Parse a BT XML file and return a flat list of actions."""
    tree = ET.parse(path)
    root = tree.getroot()

    bt = root.find("BehaviorTree")
    if bt is None:
        print("ERROR: No <BehaviorTree> element found", file=sys.stderr)
        sys.exit(1)

    seq = bt.find("Sequence")
    if seq is None:
        print("ERROR: No <Sequence> element found", file=sys.stderr)
        sys.exit(1)

    actions = []
    for child in seq:
        if child.tag == "RetryNode":
            num_attempts = int(child.get("num_attempts", "3"))
            inner = child.find("Action")
            if inner is not None:
                actions.append({
                    "type": inner.get("ID"),
                    "attrs": dict(inner.attrib),
                    "retry": num_attempts,
                })
        elif child.tag == "Action":
            actions.append({
                "type": child.get("ID"),
                "attrs": dict(child.attrib),
                "retry": 1,
            })
    return actions


def execute_dry_run(actions: list[dict]) -> bool:
    """Log all actions without sending goals."""
    print("=== DRY RUN MODE ===")
    total = len(actions)
    for i, action in enumerate(actions, 1):
        atype = action["type"]
        attrs = action["attrs"]
        if atype == "GoTo":
            print(f"[{i}/{total}] GoTo ({attrs.get('x')}, {attrs.get('y')}) "
                  f"theta={attrs.get('theta')} retries={action['retry']} — SKIPPED (dry-run)")
        elif atype == "Wait":
            print(f"[{i}/{total}] Wait {attrs.get('duration')}s — SKIPPED (dry-run)")
        elif atype == "Report":
            print(f"[{i}/{total}] Report '{attrs.get('message')}' — SKIPPED (dry-run)")
        else:
            print(f"[{i}/{total}] Unknown action: {atype} — SKIPPED (dry-run)")
    print(f"=== DRY RUN COMPLETE: {total} actions parsed ===")
    return True


def execute_live(actions: list[dict], verify_odom: bool = False) -> bool:
    """Execute actions by sending Nav2 goals via rclpy."""
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.action import ActionClient
        from geometry_msgs.msg import PoseStamped
        from nav2_msgs.action import NavigateToPose
        from std_msgs.msg import String
    except ImportError as e:
        print(f"ERROR: Missing ROS2 dependency: {e}", file=sys.stderr)
        print("This script must run inside the Docker container with ROS2 Jazzy.", file=sys.stderr)
        sys.exit(1)

    rclpy.init()
    node = Node("debug_executor")
    nav_client = ActionClient(node, NavigateToPose, "/navigate_to_pose")
    report_pub = node.create_publisher(String, "/task_reports", 10)

    print("Waiting for /navigate_to_pose action server...")
    if not nav_client.wait_for_server(timeout_sec=30.0):
        print("ERROR: /navigate_to_pose action server not available after 30s", file=sys.stderr)
        rclpy.shutdown()
        return False
    print("Action server ready.")

    total = len(actions)
    all_ok = True

    for i, action in enumerate(actions, 1):
        atype = action["type"]
        attrs = action["attrs"]

        if atype == "GoTo":
            x = float(attrs.get("x", 0))
            y = float(attrs.get("y", 0))
            theta = float(attrs.get("theta", 0))
            max_attempts = action["retry"]

            for attempt in range(1, max_attempts + 1):
                print(f"[{i}/{total}] GoTo ({x}, {y}) theta={theta} "
                      f"attempt {attempt}/{max_attempts}...")
                t0 = time.time()

                goal = NavigateToPose.Goal()
                goal.pose = PoseStamped()
                goal.pose.header.frame_id = attrs.get("frame_id", "map")
                goal.pose.header.stamp = node.get_clock().now().to_msg()
                goal.pose.pose.position.x = x
                goal.pose.pose.position.y = y
                # Convert theta to quaternion (yaw only)
                import math
                goal.pose.pose.orientation.z = math.sin(theta / 2.0)
                goal.pose.pose.orientation.w = math.cos(theta / 2.0)

                future = nav_client.send_goal_async(goal)
                rclpy.spin_until_future_complete(node, future)
                goal_handle = future.result()

                if not goal_handle.accepted:
                    print(f"  Goal REJECTED")
                    if attempt < max_attempts:
                        print(f"  Retrying in 3s...")
                        time.sleep(3.0)
                        continue
                    all_ok = False
                    break

                result_future = goal_handle.get_result_async()
                rclpy.spin_until_future_complete(node, result_future)
                elapsed = time.time() - t0

                result = result_future.result()
                if result.status == 4:  # STATUS_SUCCEEDED
                    print(f"  SUCCEEDED ({elapsed:.1f}s)")
                    if verify_odom:
                        _check_odom(node, x, y)
                    break
                else:
                    print(f"  FAILED (status={result.status}, {elapsed:.1f}s)")
                    if attempt < max_attempts:
                        print(f"  Retrying in 3s...")
                        time.sleep(3.0)
                    else:
                        all_ok = False

        elif atype == "Wait":
            duration = float(attrs.get("duration", 1.0))
            print(f"[{i}/{total}] Wait {duration}s...")
            time.sleep(duration)
            print(f"  DONE")

        elif atype == "Report":
            msg_text = attrs.get("message", "")
            print(f"[{i}/{total}] Report '{msg_text}'")
            msg = String()
            msg.data = msg_text
            report_pub.publish(msg)
            print(f"  Published to /task_reports")

        else:
            print(f"[{i}/{total}] Unknown action: {atype} — SKIPPED")

    rclpy.shutdown()
    return all_ok


def _check_odom(node, target_x: float, target_y: float, tolerance: float = 0.5):
    """Read /odom once and check position is within tolerance of target."""
    from nav_msgs.msg import Odometry
    import math

    odom_msg = None

    def _cb(msg):
        nonlocal odom_msg
        odom_msg = msg

    sub = node.create_subscription(Odometry, "/odom", _cb, 1)
    # Spin briefly to get one message
    end = time.time() + 2.0
    while odom_msg is None and time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.1)
    node.destroy_subscription(sub)

    if odom_msg is None:
        print(f"  WARN: Could not read /odom for verification")
        return

    ax = odom_msg.pose.pose.position.x
    ay = odom_msg.pose.pose.position.y
    dist = math.sqrt((ax - target_x) ** 2 + (ay - target_y) ** 2)
    if dist <= tolerance:
        print(f"  Odom check: OK (actual={ax:.2f},{ay:.2f} dist={dist:.2f}m)")
    else:
        print(f"  Odom check: WARN (actual={ax:.2f},{ay:.2f} dist={dist:.2f}m > {tolerance}m)")


def main():
    print("=" * 60)
    print("Defined Robotics — Debug BT Executor")
    print("WARNING: Debug tool only. Production uses BT.CPP (C++).")
    print("=" * 60)

    ap = argparse.ArgumentParser(description="Debug BT XML executor")
    ap.add_argument("bt_xml", help="Path to compiled BT XML file")
    ap.add_argument("--dry-run", action="store_true", help="Parse and log without sending goals")
    ap.add_argument("--verify-odom", action="store_true", help="Check /odom after each GoTo")
    args = ap.parse_args()

    actions = parse_bt_xml(args.bt_xml)
    print(f"Parsed {len(actions)} actions from {args.bt_xml}")

    if args.dry_run:
        ok = execute_dry_run(actions)
    else:
        ok = execute_live(actions, verify_odom=args.verify_odom)

    if ok:
        print("=== EXECUTOR COMPLETE: SUCCESS ===")
        sys.exit(0)
    else:
        print("=== EXECUTOR COMPLETE: FAILURE ===", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
