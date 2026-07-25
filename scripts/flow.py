#!/usr/bin/env python3
"""Shared preparation and characterization generator for packaged K-library flows."""

import argparse
import itertools
import json
import os
import re
import shutil
from pathlib import Path


SUBCKT_START = re.compile(r"^\s*\.subckt\s+(\S+)", re.I)
SUBCKT_END = re.compile(r"^\s*\.ends(?:\s+(\S+))?", re.I)


def expanded_path(value: str, base: Path) -> Path:
    value = os.path.expandvars(os.path.expanduser(value))
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def load_config(path: Path) -> dict:
    path = path.resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_config_path"] = path
    data["_config_dir"] = path.parent
    if not isinstance(data.get("cells"), list) or not data["cells"]:
        raise SystemExit("configuration must contain a non-empty cells list")
    for field in ("library_name", "output_lib", "assets"):
        if not data.get(field):
            raise SystemExit(f"configuration lacks {field}")
    return data


def asset(config: dict, name: str, required: bool = True) -> Path:
    value = config["assets"].get(name)
    if not value:
        if required:
            raise SystemExit(f"configuration assets lacks {name}")
        return None
    path = expanded_path(value, config["_config_dir"])
    if required and not path.exists():
        raise SystemExit(f"missing asset {name}: {path}")
    return path


def input_path(config: dict, cell: dict, name: str) -> Path:
    value = cell.get(name)
    if not value:
        raise SystemExit(f"{cell.get('cell_name', '<unknown>')} lacks {name}")
    path = expanded_path(value, config["_config_dir"])
    if not path.is_file():
        raise SystemExit(f"missing {name} for {cell.get('cell_name')}: {path}")
    return path


def extract_subckt(text: str, cell_name: str) -> str:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        match = SUBCKT_START.match(line)
        if match and match.group(1).lower() == cell_name.lower():
            start = index
            break
    if start is None:
        raise SystemExit(f"SUBCKT {cell_name} not found")
    for index in range(start + 1, len(lines)):
        match = SUBCKT_END.match(lines[index])
        if not match:
            continue
        end_name = match.group(1)
        if end_name and end_name.lower() != cell_name.lower():
            continue
        return "\n".join(lines[start : index + 1]) + "\n"
    raise SystemExit(f"SUBCKT {cell_name} has no matching .ENDS")


def subckt_pins(spice: str, cell_name: str) -> list:
    pieces = []
    collecting = False
    for raw in spice.splitlines():
        if not collecting:
            match = SUBCKT_START.match(raw)
            if not match or match.group(1).lower() != cell_name.lower():
                continue
            collecting = True
            pieces.append(raw.strip())
        elif raw.lstrip().startswith("+"):
            pieces.append(raw.lstrip()[1:].strip())
        else:
            break
    return " ".join(pieces).split()[2:]


def validate_cell(cell: dict, mode: str) -> None:
    required = (
        "key",
        "cell_name",
        "source_spice",
        "inputs",
        "output",
        "power_pin",
        "ground_pin",
        "nmos_models",
        "pmos_models",
        "pins",
        "truth_table",
        "function",
    )
    missing = [name for name in required if name not in cell or cell[name] in (None, "")]
    if missing:
        raise SystemExit(f"cell entry lacks {missing}: {cell}")
    if mode == "gds" and not cell.get("gds"):
        raise SystemExit(f"{cell['cell_name']}: GDS mode requires gds")
    if len(set(cell["pins"])) != len(cell["pins"]):
        raise SystemExit(f"{cell['cell_name']}: duplicate pins")
    logical_pins = cell["inputs"] + [
        cell["output"],
        cell["power_pin"],
        cell["ground_pin"],
    ]
    if any(pin not in cell["pins"] for pin in logical_pins):
        raise SystemExit(f"{cell['cell_name']}: logical pins are absent from pins")
    if len(set(logical_pins)) != len(logical_pins):
        raise SystemExit(f"{cell['cell_name']}: inferred pin roles overlap")
    expected_vectors = {
        "".join(str(bit) for bit in bits)
        for bits in itertools.product((0, 1), repeat=len(cell["inputs"]))
    }
    actual_vectors = set(cell["truth_table"])
    if actual_vectors != expected_vectors:
        raise SystemExit(
            f"{cell['cell_name']}: truth-table vectors do not match inputs; "
            f"expected={sorted(expected_vectors)}, actual={sorted(actual_vectors)}"
        )
    if any(value not in (0, 1) for value in cell["truth_table"].values()):
        raise SystemExit(f"{cell['cell_name']}: truth-table outputs must be 0 or 1")


def prepare(config: dict, work: Path, mode: str) -> None:
    rule_dir = asset(config, "rule_dir")
    pex_template = asset(config, "pex_rule_template").read_text(encoding="utf-8")
    if mode == "spice":
        asset(config, "stdgen_bin")
        asset(config, "stdgen_libs")
    seen_keys = set()
    seen_names = set()
    for cell in config["cells"]:
        validate_cell(cell, mode)
        key = cell["key"]
        cell_name = cell["cell_name"]
        if key in seen_keys or cell_name.lower() in seen_names:
            raise SystemExit(f"duplicate key or cell_name: {key}, {cell_name}")
        seen_keys.add(key)
        seen_names.add(cell_name.lower())
        source = input_path(config, cell, "source_spice")
        spice = extract_subckt(
            source.read_text(encoding="utf-8", errors="replace"),
            cell_name,
        )
        actual_pins = subckt_pins(spice, cell_name)
        if actual_pins != cell["pins"]:
            raise SystemExit(
                f"{cell_name}: SUBCKT pins {actual_pins} do not match configured {cell['pins']}"
            )

        run = work / "runs" / key
        for name in ("SDCgen", "cdl", "gds", "pex", "ruledirs", "logs"):
            (run / name).mkdir(parents=True, exist_ok=True)
        (run / "cdl" / "cell.cdl").write_text(spice, encoding="utf-8")
        for source_rule in rule_dir.iterdir():
            if source_rule.is_file():
                shutil.copy2(source_rule, run / "ruledirs" / source_rule.name)
        rcx_control = run / "ruledirs" / "rcxControl_calibre_asap7.rul"
        if rcx_control.is_file():
            rcx_text = rcx_control.read_text(encoding="utf-8")
            rcx_text = rcx_text.replace(
                "PEX EXTRACT EXCLUDE SOURCENAMES VDD VSS",
                "PEX EXTRACT EXCLUDE SOURCENAMES "
                f"{cell['power_pin']} {cell['ground_pin']}",
            )
            rcx_control.write_text(rcx_text, encoding="utf-8")
        if mode == "spice":
            stdgen_config = {
                "paths": {"cdlPath": "../cdl/cell.cdl", "outputPath": "../gds/"},
                "para": {
                    "NUM_ROWS": 1,
                    "GS_RELAX": 1,
                    "NPPN": 1,
                    "VT": 98,
                    "LG": 20,
                    "LEXT": 4,
                    "CPP": 56,
                    "TFIN": 62,
                },
            }
            (run / "SDCgen" / "config.json").write_text(
                json.dumps(stdgen_config, indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            shutil.copy2(input_path(config, cell, "gds"), run / "gds" / f"{cell_name}.gds")

        pex_rule = (
            pex_template.replace('"topCell.gds"', f'"../gds/{cell_name}.gds"')
            .replace('"topCell.cdl"', '"../cdl/cell.cdl"')
            .replace('"topCell"', f'"{cell_name}"')
            .replace('"topCell.lvs.report"', f'"{cell_name}.lvs.report"')
            .replace('"topCell.pex.netlist"', f'"{cell_name}.pex.netlist"')
            .replace('"topPower"', f'"{cell["power_pin"]}"')
            .replace('"topGround"', f'"{cell["ground_pin"]}"')
            .replace('"pex_rule"', '"../ruledirs/rcxControl_calibre_asap7.rul"')
        )
        (run / "pex" / "pex.rule").write_text(pex_rule, encoding="utf-8")
    print(f"prepared {len(config['cells'])} cells in {work}")


def logic_value(cell: dict, values: dict) -> int:
    vector = "".join(str(values[pin]) for pin in cell["inputs"])
    try:
        return int(cell["truth_table"][vector])
    except KeyError as exc:
        raise ValueError(
            f"{cell['cell_name']}: truth table lacks input vector {vector}"
        ) from exc


def input_states(inputs: list):
    for bits in itertools.product((0, 1), repeat=len(inputs)):
        yield dict(zip(inputs, bits))


def sensitized_arcs(cell: dict) -> list:
    inputs = cell["inputs"]
    arcs = []
    for related in inputs:
        side_pins = [pin for pin in inputs if pin != related]
        for side_bits in itertools.product((0, 1), repeat=len(side_pins)):
            side = dict(zip(side_pins, side_bits))
            low = dict(side, **{related: 0})
            high = dict(side, **{related: 1})
            if logic_value(cell, low) == logic_value(cell, high):
                continue
            for old, new in ((0, 1), (1, 0)):
                initial = dict(side, **{related: old})
                final = dict(side, **{related: new})
                y_initial = logic_value(cell, initial)
                y_final = logic_value(cell, final)
                vector = "".join(
                    "R"
                    if pin == related and new == 1
                    else "F"
                    if pin == related
                    else str(side[pin])
                    for pin in inputs
                ) + ("R" if y_final > y_initial else "F")
                when = " * ".join(pin if side[pin] else f"!{pin}" for pin in side_pins)
                arcs.append((related, when, vector))
    return arcs


def tcl_list(items) -> str:
    return "{" + " ".join(items) + "}"


def quote(value) -> str:
    return '"' + str(value).replace('"', '\\"') + '"'


def lvs_is_correct(report: Path) -> bool:
    text = report.read_text(encoding="utf-8", errors="replace")
    marker = text.find("OVERALL COMPARISON RESULTS")
    window = text[marker : marker + 1200] if marker >= 0 else ""
    return bool(re.search(r"#\s+CORRECT", window))


def generate_characterization(config: dict, work: Path) -> Path:
    model = asset(config, "model")
    settings = asset(config, "liberate_settings")
    char = work / "characterization"
    netlists = char / "netlists"
    for directory in (netlists, char / "output", char / "decks"):
        directory.mkdir(parents=True, exist_ok=True)

    for cell in config["cells"]:
        run_pex = work / "runs" / cell["key"] / "pex"
        name = cell["cell_name"]
        report = run_pex / f"{name}.lvs.report"
        if not report.is_file() or not lvs_is_correct(report):
            raise SystemExit(f"{name}: missing or non-CORRECT LVS report")
        required = [
            run_pex / f"{name}.pex.netlist",
            run_pex / f"{name}.pex.netlist.pex",
        ]
        pxi = list(run_pex.glob(f"{name}.pex.netlist.*.pxi"))
        if len(pxi) != 1:
            raise SystemExit(f"{name}: expected one PEX pxi file, found {len(pxi)}")
        required.extend(pxi)
        if not all(path.is_file() and path.stat().st_size for path in required):
            raise SystemExit(f"{name}: incomplete PEX file set")
        for source in required:
            shutil.copy2(source, netlists / source.name)

    output_lib = char / "output" / config["output_lib"]
    voltage = config.get("voltage", 0.7)
    temperature = config.get("temperature", 25)
    nmos_models = sorted(
        {model for cell in config["cells"] for model in cell["nmos_models"]}
    )
    pmos_models = sorted(
        {model for cell in config["cells"] for model in cell["pmos_models"]}
    )
    leafcell_lines = [
        f"define_leafcell -extsim_model -type nmos -pin_position {{0 1 2 3}} "
        f"{{{model}}}"
        for model in nmos_models
    ]
    leafcell_lines.extend(
        f"define_leafcell -extsim_model -type pmos -pin_position {{0 1 2 3}} "
        f"{{{model}}}"
        for model in pmos_models
    )
    lines = [
        "set rundir $env(PWD)",
        f"set LIBNAME {config['library_name']}",
        f"set VDD_VALUE {voltage}",
        f"set TEMP {temperature}",
        f"set MODEL_INCLUDE_FILE {quote(model)}",
        f"source {quote(settings)}",
        "set ALTOS_QUEUE 1",
        "set ALTOS_LIC_MAX_TIMEOUT 60",
        "set_var extsim_deck_dir ${rundir}/decks",
        "set_var extsim_save_failed all",
        "set_var power_info 2",
        "set_var power_info_filename ${rundir}/output/power_tc.log",
        "set_units -timing 1ps -capacitance 1ff -leakage_power 1pW",
        "set_var slew_lower_rise 0.1",
        "set_var slew_lower_fall 0.1",
        "set_var slew_upper_rise 0.9",
        "set_var slew_upper_fall 0.9",
        "set_var measure_slew_lower_rise 0.1",
        "set_var measure_slew_lower_fall 0.1",
        "set_var measure_slew_upper_rise 0.9",
        "set_var measure_slew_upper_fall 0.9",
        "set_var delay_inp_rise 0.5",
        "set_var delay_inp_fall 0.5",
        "set_var delay_out_rise 0.5",
        "set_var delay_out_fall 0.5",
        "set_var def_arc_msg_level 0",
        "set_var process_match_pins_to_ports 1",
        "set_var max_transition 3.2e-10",
        "set_var min_transition 5e-12",
        "set_var min_output_cap 3.6e-16",
        "set_var mega_short_circuit_mode 2",
        "define_template -type delay -index_1 {0.005 0.01 0.02 0.04 0.08 0.16 0.32} -index_2 {0.00072 0.00144 0.00288 0.00576 0.01152 0.02304 0.04608} delay_template_7x7_x1",
        "define_template -type power -index_1 {0.005 0.01 0.02 0.04 0.08 0.16 0.32} -index_2 {0.00072 0.00144 0.00288 0.00576 0.01152 0.02304 0.04608} power_template_7x7_x1",
        "set cells {",
    ]
    lines.extend(f"  {cell['cell_name']}" for cell in config["cells"])
    lines.extend(
        [
            "}",
            "set_operating_condition -voltage ${VDD_VALUE} -temp ${TEMP}",
            "set_var extsim_model_include ${MODEL_INCLUDE_FILE}",
            *leafcell_lines,
            "set spicefiles [list ${MODEL_INCLUDE_FILE}]",
            "foreach cell $cells { lappend spicefiles ${rundir}/netlists/${cell}.pex.netlist }",
            "set saved_pwd [pwd]",
            "cd ${rundir}/netlists",
            "read_spice -format spectre $spicefiles",
            "cd ${saved_pwd}",
            "set_var prevector_period 5e-10",
            "set prevector_voltage_waveform_mode 2",
            "set_var prevector_slew min",
            "set_var default_timing off",
            "set_var default_power off",
        ]
    )
    for cell in config["cells"]:
        name = cell["cell_name"]
        inputs = cell["inputs"]
        output = cell["output"]
        lines.append(
            f"# inferred topology: {output} = {cell['function']}; "
            f"power={cell['power_pin']}; ground={cell['ground_pin']}"
        )
        lines.append(
            f"define_cell -input {tcl_list(inputs)} -output {tcl_list([output])} "
            f"-pinlist {tcl_list(inputs + [output])} -delay delay_template_7x7_x1 "
            f"-power power_template_7x7_x1 {name}"
        )
        for state in input_states(inputs):
            y = logic_value(cell, state)
            terms = [pin if state[pin] else f"!{pin}" for pin in inputs]
            terms.append(output if y else f"!{output}")
            lines.append(f"define_leakage -when {quote('(' + ' * '.join(terms) + ')')} {name}")
        for related, when_value, vector in sensitized_arcs(cell):
            when = f" -when {quote(when_value)}" if when_value else ""
            lines.append(
                f"define_arc{when} -vector {tcl_list([vector])} "
                f"-related_pin {related} -pin {output} {name}"
            )
    threads = int(config.get("threads", 8))
    lines.extend(
        [
            f"set char_threads {threads}",
            "if {[info exists ::env(CHAR_THREADS)]} { set char_threads $::env(CHAR_THREADS) }",
            "char_library -user_arcs_only -extsim spectre -cells ${cells} -thread ${char_threads}",
            f"write_library -thread ${{char_threads}} -overwrite -filename {quote(output_lib)} ${{LIBNAME}}",
            "exit",
        ]
    )
    tcl = char / "char.tcl"
    tcl.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(tcl)
    return tcl


def list_cells(config: dict) -> None:
    for cell in config["cells"]:
        print(f"{cell['key']}\t{cell['cell_name']}")


def show_asset(config: dict, name: str) -> None:
    print(asset(config, name))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "generate-char", "list", "asset"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--mode", choices=("spice", "gds"))
    parser.add_argument("--name")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "list":
        list_cells(config)
        return 0
    if args.command == "asset":
        if not args.name:
            parser.error("asset requires --name")
        show_asset(config, args.name)
        return 0
    if not args.work_dir:
        parser.error(f"{args.command} requires --work-dir")
    work = args.work_dir.resolve()
    if args.command == "prepare":
        if not args.mode:
            parser.error("prepare requires --mode")
        prepare(config, work, args.mode)
    else:
        generate_characterization(config, work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
