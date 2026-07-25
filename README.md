# ASAP7 GDS to Liberty

本仓库包含从标准单元 GDS 生成 Liberty 所需的脚本、ASAP7 Calibre rule、器件模型和 Liberate 设置。

用户需要提供：

- `input/` 下同名的标准单元 GDS 和晶体管级 SPICE/CDL；
- 安装了 `centos7-stdcell` Docker 镜像的宿主机；
- 可用的 Calibre、Liberate 和 Spectre 许可证环境。

## 执行

把输入SPICE与GDS放到 `input/`，如：

```text
input/AND2x2_ASAP7_6t_L.sp
input/AND2x2_ASAP7_6t_L.gds
```

运行时只需提供 cell 名：

```bash
./run.sh AND2x2_ASAP7_6t_L
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
./run.sh AND2x2_ASAP7_6t_L \
  --library-name ASAP7_SELECTED_POSTLAYOUT \
  --output-lib asap7_selected_postlayout.lib
```

其他配置生成参数：

- `--skip-unsupported`：跳过无法自动识别的子电路；
- `--voltage VALUE`：表征电压，默认 `0.7` V；
- `--temperature VALUE`：表征温度，默认 `25` °C；
- `--threads N`：Liberate 并发线程数，默认 `8`；
- `--library-name NAME`：Liberty library 名称，默认使用当前单元名；
- `--output-lib FILE`：输出 Liberty 文件名，默认使用 `<单元名>.lib`。

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

## 内置工艺条件

- 工艺：ASAP7_6t_L；
- 默认电压：0.7 V；
- 默认温度：25 °C；
- delay/power template：7 个输入 slew × 7 个输出负载；
- Liberty area 根据 GDS 非文本几何宽度和 ASAP7 6-track 固定高度 `0.216 µm` 计算。
