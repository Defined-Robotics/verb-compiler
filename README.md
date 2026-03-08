# defined-compiler

Verb language compiler for Defined Robotics. Compiles high-level task YAML files into [BehaviorTree.CPP](https://www.behaviortree.dev/) XML, with compile-time capability validation against the robot's RDF descriptor.

## How it works

```
robot.rdf.yaml   ──┐
                   ├──► defined-compile ──► task.bt.xml
task.yaml        ──┤
verbs/ directory ──┘
```

1. **Parse** the task YAML (a sequence of named verb steps with parameters)
2. **Expand** each verb by loading its definition from the verbs directory
3. **Gate** each verb against the robot's declared capabilities (from the RDF); compilation fails fast if a capability is missing
4. **Emit** a valid BehaviorTree.CPP XML file by rendering each verb's Jinja2 template

## Installation

```bash
pip install defined-compiler
```

Or in a `uv` workspace:

```bash
uv sync --package defined-compiler
```

`defined-rdf` is a required dependency and is installed automatically.

## CLI usage

```bash
defined-compile <task.yaml> --rdf <robot.rdf.yaml> [--verbs-dir <path>] [-o <output.xml>]
```

| Argument | Description |
|---|---|
| `task.yaml` | Task file to compile (positional) |
| `--rdf` | Path to the robot RDF YAML (required) |
| `--verbs-dir` | Directory containing verb `.yaml` and `.xml.j2` files (default: built-in `verb_library/`) |
| `-o / --output` | Write XML to file instead of stdout |

### Example

```bash
defined-compile tasks/patrol.task.yaml \
    --rdf robot.rdf.yaml \
    --verbs-dir verbs/ \
    -o patrol.bt.xml
```

## Task file format

```yaml
name: PatrolTask
description: "Patrol between three waypoints"

steps:
  - verb: go_to
    params:
      x: 1.0
      y: 0.0
      theta: 0.0
  - verb: report
    params:
      message: "arrived_at_wp1"
  - verb: wait
    params:
      duration: 2.0
```

## Verb definition format

Each verb is defined by two files in the verbs directory:

**`go_to.yaml`** — verb metadata:
```yaml
name: go_to
description: "Navigate the robot to a specified position"
required_capabilities:
  - differential_drive
template: go_to.xml.j2
primitives:
  - navigate_to_pose
parameters:
  x:
    type: float
    required: true
  y:
    type: float
    required: true
  theta:
    type: float
    required: false
    default: 0.0
```

**`go_to.xml.j2`** — Jinja2 template rendered into the BT XML:
```xml
<Action ID="GoTo" name="go_to_{{ x }}_{{ y }}"
    x="{{ x }}" y="{{ y }}" theta="{{ theta | default('0.0') }}" />
```

### Built-in verbs

| Verb | Required capabilities | Parameters |
|---|---|---|
| `go_to` | `differential_drive` | `x`, `y`, `theta` (optional, default 0.0) |
| `wait` | — | `duration` (seconds) |
| `report` | — | `message` (optional, default `"checkpoint"`) |

## Capability validation

At compile time, each verb's `required_capabilities` list is checked against the capabilities declared in the robot's RDF file. If any capability is missing, compilation aborts with a clear error:

```
REJECTED: verb 'go_to' requires capabilities ['differential_drive']
not available on robot 'my_robot'
```

This prevents invalid task XML from ever reaching the runtime.

## Python API

```python
from pathlib import Path
from defined_rdf.parser import load as load_rdf
from defined_rdf.registry import CapabilityRegistry
from defined_compiler import parser, verb_expander, capability_gate, bt_emitter

robot = load_rdf("robot.rdf.yaml")
registry = CapabilityRegistry(robot)
task = parser.load_task("tasks/patrol.task.yaml")
verbs_dir = Path("verbs/")

expanded = []
for step in task["steps"]:
    verb_data = verb_expander.expand_verb(step["verb"], step.get("params", {}), verbs_dir=verbs_dir)
    result = capability_gate.check(registry, verb_data["required_capabilities"])
    if not result.passed:
        raise RuntimeError(f"Missing capabilities: {result.missing}")
    expanded.append(verb_data)

xml = bt_emitter.render_bt_xml(expanded, task_name=task["name"], verbs_dir=verbs_dir)
print(xml)
```

## Development

```bash
uv sync
uv run pytest
```

## License

Apache-2.0
