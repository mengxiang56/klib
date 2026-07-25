# ASAP7 GDS 到 Liberty 独立流程

本仓库包含从标准单元 GDS 生成 Liberty 所需的全部流程脚本、ASAP7 Calibre rule、
器件模型和 Liberate 设置。默认情况下不会读取本仓库之外的工艺文件。

用户只需要提供：

- `input/` 下同名的标准单元 GDS 和晶体管级 SPICE/CDL；
- 安装了 `centos7-stdcell` Docker 镜像的宿主机；
- 可用的 Calibre、Liberate 和 Spectre 许可证环境。

## 一键运行

把同名输入文件放到 `input/`，例如：

```text
input/NAND2x1_ASAP7_6t_L.sp
input/NAND2x1_ASAP7_6t_L.gds
```

运行时只需提供 cell 名：

```bash
./run.sh NAND2x1_ASAP7_6t_L
```

`input/` 还包含一个不属于旧固定类型列表的 AND2 示例，用于验证 MOS 拓扑推断：

```bash
./input/run_and2_example.sh
```

该例会自动推导出 `Y = A * B`。GDS/CDL 来自 OpenROAD 官方
`asap7sc6t_26` LVT 标准库的 `390b499` 版本，并从完整标准库中提取为单-cell 输入。

示例输出位于：

```text
lib-NAND2x1_ASAP7_6t_L/characterization/output/NAND2x1_ASAP7_6t_L.lib
```

完整执行链：

```text
SPICE/CDL + GDS
  -> 根据 MOS 拓扑自动识别输入、输出、电源和地
  -> 枚举输入并生成真值表、布尔函数和 timing arc
  -> 自动生成 cells.generated.json
  -> Calibre LVS
  -> Calibre xACT PEX
  -> Liberate 调用 Spectre 进行 7x7 表征
  -> 从 GDS 计算并回填 cell area
  -> Liberty .lib
```

最终 Liberty 位于：

```text
lib-<cell名>/characterization/output/my_asap7_postlayout.lib
```

## 设置库名

配置生成参数直接跟在 cell 名后：

```bash
./run.sh NAND2x1_ASAP7_6t_L \
  --library-name ASAP7_SELECTED_POSTLAYOUT \
  --output-lib asap7_selected_postlayout.lib
```

其他配置生成参数：

- `--skip-unsupported`：跳过无法自动识别的子电路；
- `--voltage VALUE`：表征电压，默认 `0.7` V；
- `--temperature VALUE`：表征温度，默认 `25` °C；
- `--threads N`：Liberate 并发线程数，默认 `8`；
- `--library-name NAME`：Liberty library 名称；
- `--output-lib FILE`：输出 Liberty 文件名。

流程会分析 MOS 的 gate/source/drain/bulk 连接：

- PMOS 的唯一公共 bulk 网络识别为电源；
- NMOS 的唯一公共 bulk 网络识别为地；
- 只连接 MOS gate 的外部功能端口识别为输入；
- 同时连接 PMOS/NMOS diffusion 的唯一外部功能端口识别为输出；
- 枚举所有输入组合，通过导通网络求出真值表和布尔函数；
- timing arc 和 leakage 状态由推断出的真值表生成。

输入网表需要满足：

- cell 是平坦、静态、单输出 CMOS 组合逻辑；
- `.SUBCKT` 内只包含 MOS 实例，不依赖层次化子电路或其他器件；
- MOS 模型名包含 `nmos`/`pmos` 或 `nfet`/`pfet`；
- 所有 PMOS 使用同一个 bulk 电源端口，所有 NMOS 使用同一个 bulk 地端口；
- 外部输入只连接 MOS gate，不连接 source/drain；
- 每个输入组合下输出都有唯一、无冲突的稳定逻辑值。

SPICE 中需存在同名 `.SUBCKT`，且 GDS 文件名和 GDS 内部 primary cell 需要与它一致，例如：

```text
NAND2x1_ASAP7_6t_L.gds
.SUBCKT NAND2x1_ASAP7_6t_L A B VDD VSS Y
```

## Docker 与许可证

默认 Docker 镜像：

```bash
centos7-stdcell
```

如果宿主机使用其他镜像名：

```bash
export KLIB_DOCKER_IMAGE=centos-stdcell
```

入口会把以下许可证变量传入容器：

```bash
LM_LICENSE_FILE
CDS_LIC_FILE
```

示例：

```bash
export LM_LICENSE_FILE=port@license-server
export CDS_LIC_FILE=port@license-server
```

如果已经进入包含 EDA 工具的容器，可跳过 Docker 外壳：

```bash
export KLIB_EXECUTION=local
./run.sh NAND2x1_ASAP7_6t_L
```

## 仓库内容

```text
gds-to-lib-standalone/
├── run.sh
├── README.md
├── input/
│   ├── NAND2x1_ASAP7_6t_L.gds
│   ├── NAND2x1_ASAP7_6t_L.sp
│   ├── AND2x2_ASAP7_6t_L.gds
│   ├── AND2x2_ASAP7_6t_L.sp
│   ├── run_and2_example.sh
│   └── run_example.sh
├── assets/
│   ├── models/
│   │   └── 7nm_TT_160803.pm
│   ├── reference/
│   │   ├── pex.rule
│   │   └── settings.tcl
│   ├── ruledirs/
│   │   ├── layer.inc
│   │   ├── lvsRules_calibre_asap7.rul
│   │   ├── pexMap_calibre_asap7.rul
│   │   ├── rcxControl_calibre_asap7.rul
│   │   ├── rcxRules_calibre_asap7.FS
│   │   └── rcxRules_calibre_asap7.xact
│   └── scripts/
│       └── calc_lib_area.py
└── scripts/
    ├── generate_cell_config.py
    ├── flow.py
    ├── run_in_docker.sh
    └── run_pipeline.sh
```

## 内置工艺条件

- 工艺模型：当前项目使用的 ASAP7 TT 模型；
- 默认电压：0.7 V；
- 默认温度：25 °C；
- delay/power template：7 个输入 slew × 7 个输出负载；
- timing、transition、internal power、pin capacitance 和 leakage 均由
  Liberate/Spectre 基于 PEX 网表生成；
- Liberty area 根据 GDS 非文本几何宽度和 ASAP7 6-track 固定高度 `0.216 µm` 计算。
