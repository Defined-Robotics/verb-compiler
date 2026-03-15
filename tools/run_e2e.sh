#!/usr/bin/env bash
# run_e2e.sh — End-to-end integration test: compile, launch sim, execute patrol, verify.
#
# Usage:
#   ./tools/run_e2e.sh              # Full run (compile + sim + execute + verify)
#   ./tools/run_e2e.sh --dry-run    # Compile + parse-only (no Docker needed)
#   ./tools/run_e2e.sh --skip-sim   # Skip sim startup (assumes sim already running)
#
# Run from: work/verb-compiler/
# Requires: venv activated (for compile step), Docker (for sim steps)

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPILER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLATFORM_ROOT="$(cd "$COMPILER_ROOT/../defined_platform" && pwd)"
RDF_FILE="$COMPILER_ROOT/../rdf/examples/turtlebot3_burger.rdf.yaml"
TASK_FILE="$COMPILER_ROOT/examples/patrol_task.yaml"
VERBS_DIR="$COMPILER_ROOT/verb_library"
BUILD_DIR="$COMPILER_ROOT/build"
BT_XML="$BUILD_DIR/PatrolTask.xml"
URDF_OUT="$BUILD_DIR/robot.urdf.xacro"
COMPOSE_FILE="$PLATFORM_ROOT/docker/docker-compose.yml"
CONTAINER="defined_sim"

DRY_RUN=false
SKIP_SIM=false
VERIFY_ODOM=false

for arg in "$@"; do
    case "$arg" in
        --dry-run)    DRY_RUN=true ;;
        --skip-sim)   SKIP_SIM=true ;;
        --verify-odom) VERIFY_ODOM=true ;;
        --help|-h)
            echo "Usage: $0 [--dry-run] [--skip-sim] [--verify-odom]"
            echo ""
            echo "  --dry-run       Compile + parse BT XML only (no Docker)"
            echo "  --skip-sim      Skip sim startup (assumes container running)"
            echo "  --verify-odom   Check /odom position after each GoTo"
            exit 0
            ;;
        *) echo "Unknown arg: $arg"; exit 1 ;;
    esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
info() { echo -e "${CYAN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

FAILURES=0
record() {
    if [ $1 -eq 0 ]; then
        pass "$2"
    else
        fail "$2"
        FAILURES=$((FAILURES + 1))
    fi
}

# ---------------------------------------------------------------------------
# Step 1: Compile patrol task → BT XML
# ---------------------------------------------------------------------------
echo ""
echo "================================================================"
echo " Step 1: Compile patrol task -> BT XML"
echo "================================================================"

mkdir -p "$BUILD_DIR"

info "Compiling $TASK_FILE ..."
defined-compile "$TASK_FILE" \
    --rdf "$RDF_FILE" \
    --verbs-dir "$VERBS_DIR" \
    -o "$BT_XML"
record $? "BT XML compiled to $BT_XML"

# Quick validation: well-formed XML with expected structure
python3 -c "
import xml.etree.ElementTree as ET, sys
root = ET.parse('$BT_XML').getroot()
assert root.get('BTCPP_format') == '4', 'Not BTCPP_format 4'
seq = root.find('BehaviorTree/Sequence')
n = len(list(seq))
assert n == 8, f'Expected 8 children, got {n}'
print(f'  BT XML valid: {n} actions in Sequence')
"
record $? "BT XML structure validated (8 actions)"

# ---------------------------------------------------------------------------
# Step 2: Generate URDF from RDF
# ---------------------------------------------------------------------------
echo ""
echo "================================================================"
echo " Step 2: Generate URDF xacro from RDF"
echo "================================================================"

info "Generating URDF from $RDF_FILE ..."
defined-compile \
    --generate-urdf \
    --rdf "$RDF_FILE" \
    -o "$URDF_OUT"
record $? "URDF xacro generated to $URDF_OUT"

# Validate: Gz Sim plugins present, no Gazebo Classic
python3 -c "
import re, xml.etree.ElementTree as ET, sys
with open('$URDF_OUT') as f:
    text = f.read()

# Strip xacro namespace for parsing
text_clean = re.sub(r'\s+xmlns:xacro=\"[^\"]*\"', '', text)
text_clean = re.sub(r'<xacro:property[^/]*/>', '', text_clean)
root = ET.fromstring(text_clean)

# Check for Gz Sim diff drive
found_dd = False
for gz in root.findall('gazebo'):
    for p in gz.findall('plugin'):
        if 'diff-drive' in (p.get('filename') or ''):
            found_dd = True
assert found_dd, 'gz-sim-diff-drive-system not found'
print('  Gz Sim diff-drive plugin: OK')

# Check for gpu_lidar
found_lidar = False
for gz in root.findall('gazebo'):
    for s in gz.findall('sensor'):
        if s.get('type') == 'gpu_lidar':
            found_lidar = True
            assert s.find('gz_frame_id') is not None, 'Missing gz_frame_id'
assert found_lidar, 'gpu_lidar sensor not found'
print('  Gz Sim gpu_lidar sensor: OK')

# No Gazebo Classic
assert 'libgazebo_ros' not in text, 'Found Gazebo Classic plugin references'
print('  No Gazebo Classic plugins: OK')
"
record $? "URDF validated (Gz Sim plugins, no Classic)"

# ---------------------------------------------------------------------------
# Dry-run mode: parse BT XML with debug executor and exit
# ---------------------------------------------------------------------------
if $DRY_RUN; then
    echo ""
    echo "================================================================"
    echo " Step 3 (dry-run): Parse BT XML with debug executor"
    echo "================================================================"

    python3 "$SCRIPT_DIR/debug_executor.py" "$BT_XML" --dry-run
    record $? "Debug executor dry-run"

    echo ""
    echo "================================================================"
    if [ $FAILURES -eq 0 ]; then
        pass "DRY RUN COMPLETE: all checks passed"
    else
        fail "DRY RUN COMPLETE: $FAILURES check(s) failed"
    fi
    echo "================================================================"
    exit $FAILURES
fi

# ---------------------------------------------------------------------------
# Step 3: Start simulation (or verify it's running)
# ---------------------------------------------------------------------------
echo ""
echo "================================================================"
echo " Step 3: Start simulation"
echo "================================================================"

if $SKIP_SIM; then
    info "Skipping sim startup (--skip-sim)"
else
    # Check if container is already running
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
        warn "Container $CONTAINER already running. Use --skip-sim to skip startup."
        info "Stopping existing container..."
        docker compose -f "$COMPOSE_FILE" down
        sleep 2
    fi

    info "Starting sim stack (headless)..."
    docker compose -f "$COMPOSE_FILE" up -d --build
    info "Waiting for container to start..."
    sleep 5
fi

# Verify container is running
docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"
record $? "Container $CONTAINER is running"

# ---------------------------------------------------------------------------
# Step 4: Wait for Nav2 to be ready
# ---------------------------------------------------------------------------
echo ""
echo "================================================================"
echo " Step 4: Wait for Nav2 readiness"
echo "================================================================"

info "Waiting for Nav2 action server (up to 120s)..."

NAV2_READY=false
for i in $(seq 1 24); do
    if docker exec "$CONTAINER" bash -c \
        "source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash 2>/dev/null; ros2 action list 2>/dev/null" \
        | grep -q "/navigate_to_pose"; then
        NAV2_READY=true
        break
    fi
    echo "  ... attempt $i/24 (waiting 5s)"
    sleep 5
done

if $NAV2_READY; then
    record 0 "/navigate_to_pose action server available"
else
    record 1 "/navigate_to_pose action server NOT available after 120s"
    fail "Nav2 not ready. Check: docker logs $CONTAINER"
    exit 1
fi

# Check lifecycle states
info "Checking Nav2 lifecycle nodes..."
for NODE in /controller_server /planner_server /bt_navigator; do
    docker exec "$CONTAINER" bash -c \
        "source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash 2>/dev/null; \
         ros2 lifecycle get $NODE 2>/dev/null" | tee /dev/stderr | grep -q "active"
    record $? "$NODE is active"
done

# Check TF is publishing
docker exec "$CONTAINER" bash -c \
    "source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash 2>/dev/null; \
     timeout 5 ros2 topic echo /tf --once 2>/dev/null" > /dev/null 2>&1
record $? "TF frames are being broadcast"

# Check odom
docker exec "$CONTAINER" bash -c \
    "source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash 2>/dev/null; \
     timeout 5 ros2 topic echo /odom --once 2>/dev/null" > /dev/null 2>&1
record $? "/odom topic is publishing"

# ---------------------------------------------------------------------------
# Step 5: Run debug executor
# ---------------------------------------------------------------------------
echo ""
echo "================================================================"
echo " Step 5: Run debug executor (patrol task)"
echo "================================================================"

EXECUTOR_FLAGS=""
if $VERIFY_ODOM; then
    EXECUTOR_FLAGS="--verify-odom"
fi

info "Executing patrol task via debug executor..."
docker exec "$CONTAINER" bash -c \
    "source /opt/ros/jazzy/setup.bash && \
     source /ros2_ws/install/setup.bash 2>/dev/null && \
     python3 /tools/debug_executor.py /bt_xml/PatrolTask.xml $EXECUTOR_FLAGS"
EXEC_RC=$?
record $EXEC_RC "Debug executor completed patrol"

# ---------------------------------------------------------------------------
# Step 6: Verify reports were published
# ---------------------------------------------------------------------------
echo ""
echo "================================================================"
echo " Step 6: Verify /task_reports"
echo "================================================================"

info "Checking /task_reports topic (5s window)..."
REPORTS=$(docker exec "$CONTAINER" bash -c \
    "source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash 2>/dev/null; \
     timeout 5 ros2 topic echo /task_reports std_msgs/msg/String 2>/dev/null" || true)

if echo "$REPORTS" | grep -q "arrived_at_wp1"; then
    record 0 "Report: arrived_at_wp1"
else
    record 1 "Report: arrived_at_wp1 NOT found"
fi
if echo "$REPORTS" | grep -q "patrol_complete"; then
    record 0 "Report: patrol_complete"
else
    record 1 "Report: patrol_complete NOT found"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "================================================================"
if [ $FAILURES -eq 0 ]; then
    echo -e " ${GREEN}ALL CHECKS PASSED${NC}"
else
    echo -e " ${RED}$FAILURES CHECK(S) FAILED${NC}"
fi
echo "================================================================"
echo ""
echo "Compiled artifacts:"
echo "  BT XML : $BT_XML"
echo "  URDF   : $URDF_OUT"
echo ""
echo "Sim container: $CONTAINER"
echo "  Foxglove: ws://localhost:8765"
echo "  rosbridge: ws://localhost:9090"
echo ""
if ! $SKIP_SIM; then
    echo "To stop the sim:  docker compose -f $COMPOSE_FILE down"
fi

exit $FAILURES
