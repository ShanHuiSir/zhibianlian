# 智变链｜工程变更影响分析智能体

![智变链 Logo](brand/智变链-横版.png)

本仓库保存参赛原型的源码、模拟输入、演示视频、需求基线和复盘资料。需要回顾项目时，先读 [项目复盘](docs/项目复盘.md)；需求与实现之间的差异见 [版本范围说明](docs/版本范围说明.md)。

- [演示视频（MP4，约 4 分 19 秒）](https://github.com/ShanHuiSir/zhibianlian/releases/download/v1.0.0/demo-v1.0.mp4) · [视频解说词](docs/demo/视频解说词.md)
- [原始 PRD v1.0](docs/product/PRD-v1.0.md) · [测试与实测记录](docs/测试与实测记录.md)
- [示例评审报告](docs/示例评审报告.pdf) · [示例部门处理清单](docs/示例部门处理清单.csv)
- [Logo 素材与说明](brand/使用说明.md)

视频为 2026-09-15 的实际操作录像；原始实测记录保留当时的模型配置，不代表当前供应商仍提供相同模型。运行前请按当前平台支持情况配置模型。公开仓库不含密钥、个人数据库或申报人个人材料。

开放创新赛道参赛原型 v1.0.0。面向工程变更评审，读取新旧图纸，比较尺寸与公差，沿明确业务关联检查检验、库存、在制品和订单，形成有原文依据的人工评审报告。

**可以实际运行，不是静态页面。** DeepSeek V4.1 Flash 负责图纸字段提取，Python 十进制规则引擎负责计算与关联，人负责确认生效范围、核查证据及作出评审决定。全部随附业务资料为模拟数据。

## 1. 快速启动

需要 Python 3.11 或 3.12、Chrome / Edge，以及首次安装依赖时可用的网络。已验证环境为 macOS + Python 3.12 + Chrome；Windows 启动脚本已提供，尚未在 Windows 实机验证。服务默认只监听 `127.0.0.1:8765`。

中文字体使用 Git LFS 保存。先按 [Git LFS 官方说明](https://git-lfs.com/) 安装 Git LFS（macOS 可用 `brew install git-lfs`），再运行下面的克隆步骤。`git lfs pull` 用于确保下载的是完整字体。直接下载仓库 ZIP 时可能只包含字体的 LFS 指针，请优先使用 Git 克隆。

演示视频从 [Release](https://github.com/ShanHuiSir/zhibianlian/releases/tag/v1.0.0) 下载。仓库同时保留视频的原始二进制分片；运行 `python3 tools/restore_demo.py`（Windows 用 `py tools/restore_demo.py`）可校验并还原为 `docs/demo/demo-v1.0.mp4`。还原视频不需要模型密钥或第三方 Python 依赖。

macOS / Linux：

```bash
git lfs install
git clone https://github.com/ShanHuiSir/zhibianlian.git
cd zhibianlian
git lfs pull
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# 用本机文本编辑器填写 .env 中的 DEEPSEEK_API_KEY
.venv/bin/python app.py
```

Windows PowerShell：

```powershell
git lfs install
git clone https://github.com/ShanHuiSir/zhibianlian.git
cd zhibianlian
git lfs pull
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
.\.venv\Scripts\python app.py
```

在浏览器打开 **http://127.0.0.1:8765**。也可在首次配置完成后使用 `启动.command` 或 `启动.bat`；它们会检查/安装依赖后运行服务。终端按 Ctrl+C 停止。

源码包不含密钥、个人配置、虚拟环境或本机数据库。不要把 `.env` 放进提交包或版本管理。如果不配置模型，可主动选择“本地规则 · 未调用模型”验证业务流程；界面与报告会一直标明这一点。

## 2. DeepSeek 配置

`.env` 内容：

```dotenv
DEEPSEEK_API_KEY=在此填写自己的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

2026-09-15 查阅 DeepSeek 官方文档确认：`deepseek-flash` 对应 DeepSeek-V4.1-Flash，支持图像输入。接口采用 `/chat/completions`，将 PDF 页面渲染为 PNG 后随文本发送，JSON 输出模式，关闭思考模式，输出上限 5000 tokens。配置修改后对下一轮分析生效，无需重启。环境变量优先于 `.env`。`ZBL_PORT` 通过进程环境变量设置；默认 8765。

- 模型列表：https://api-docs.deepseek.com/quick_start/pricing
- 视觉输入：https://api-docs.deepseek.com/guides/vision
- 思考模式：https://api-docs.deepseek.com/guides/thinking_mode

每轮开始前会提示：**当前新旧图纸的页面图片和解析文本发送到 DeepSeek**。BOM、库存等表格在本地解析并关联，不发送给模型。没有模型密钥或模型调用失败时，明确报错，绝不静默返回离线答案。费用以平台账单为准，程序记录 token 使用量，不伪造费用数值。

上传资料仅作为数据。模型没有执行命令、读任意本机路径或修改业务系统的工具。原型是本机单人应用，不应直接暴露为公网或多人服务。

## 3. 完整演示流程

1. 新建任务，名称任意，料号 `HSG-001`，版本 `A → B`，选择 DeepSeek 真实识图。
2. 点击“载入完整模拟案例”。这会实际导入 `samples/` 中的 8 份资料，**不会载入固定分析结果**。也可逐份上传对应文件并选择资料角色。
3. 对 BOM、检验标准、库存、在制品、订单分别打开“字段映射”，核查样例行后确认保存。
4. 打开 `ECN-001.txt` 核查原文。生效订单输入 `SO-NEW-001`，依据填写“按 ECN-001 第 3 段，仅 SO-NEW-001 使用 B 版”，点击确认生效清单。
5. 开始分析并确认发送。依次查看新旧尺寸、双向原图证据、影响清单、订单范围和资料覆盖。
6. 预期：H1 从 `4.0 ±0.1 mm` 到 `4.5 ±0.1 mm`，增加 `0.5 mm`；检验项 `QI-001` 不一致；旧库存 600 件、在制品 200 件分别待核查；B 版库存与无关料号不误报；`SO-OLD-001` 在生效范围外。
7. 对尺寸事实和检验建议选择采纳；对工艺、库存、在制品选择待核查，填写责任部门和待补资料。完成评审后导出 PDF 与 CSV。
8. 验证非固定答案：在资料页明确替换新版图纸为 `samples/variants/HSG-001_B_5mm.pdf`，再次调用 DeepSeek，差值应变为 `1 mm`。这是独立扰动验证，ECN 保留原通知，不能将这次变更当成生产批准。前一轮报告保持原来的 `0.5 mm`。

“已评审”只表示本轮意见整理完成；待核查事项仍未关闭，不表示动作已执行、生产批准或企业验证通过。

## 4. 输入契约与限制

支持 PDF、UTF-8 CSV、XLSX、DOCX 正文/表格和 TXT。新旧图纸推荐 PDF；业务表格使用 CSV/XLSX。文件总量最多 10 份、单份 20 MB、合计 100 MB、PDF 合计 30 页、业务表格合计 1000 条数据记录。加密 PDF、非法格式、过量解压内容、含公式的 XLSX 会拒绝。XLSX 编号列应设置为文本，避免表格软件先丢失前导零。

字段映射在导入后人工确认；示例使用英文标准字段，可映射常用中文表头。未知字段允许保留，但不用于规则推导。料号、版本、记录编号区分大小写，仅去首尾空格。

| 资料 | 必需字段 | 常用补充字段 |
| --- | --- | --- |
| BOM | record_id, product_no, product_rev, part_no, revision, quantity | — |
| 检验标准 | item_id, part_no, feature_id, revision, nominal, unit | lower, upper, order_id |
| 库存 | record_id, batch, part_no, revision, quantity | order_id |
| 在制品 | record_id, work_order, part_no, revision, quantity | order_id |
| 订单 | record_id, order_id, part_no, revision, quantity | — |

检验表 `revision` 表示当前标准对应版本，`order_id` 表示拟适用订单。若拟适用订单已被人工确认为新版生效订单，即检查当前标准与新版图纸的一致性。

尺寸支持 `diameter` / `length` 及 mm、cm、m、inch，公差用带符号下/上偏差。缺公差保留未知，缺单位或版本冲突要求补充。图纸特征须有明确编号，如 H1；不自动推断几何新增/删除。

本地模式只解析实际文件中的标准标注：

```text
PART: HSG-001
REV: B
FEATURE H1 diameter 4.5 mm LOW -0.1 HIGH +0.1
```

该格式用于离线复现规则。DeepSeek 模式实际发送图像和文字提取字段，随后校验字段、页码、引用和数值。对无文字层的扫描图或引用不能自动核验的标注，要求人工对照页面确认；它不是通用 CAD/OCR 替代品。

## 5. 状态、复核与导出

- 输入修改使旧结果成为历史；旧决定不带入新运行。每轮保存文件 SHA-256、配置、提取结果、修正记录、阶段时间与使用量。
- 同任务重复点击开始返回同一活动运行；全局一次仅有一轮活动分析。
- 模型单次最多等待 120 秒，超时、连接异常、429/5xx 最多重试一次；鉴权失败不重试。整轮总限时 10 分钟。
- 取消立即更新本机状态，晚到响应不能回写。重启后未完成的运行标为失败，不伪装完成。
- 库存与在制品分开统计。重复记录编号内容相同去重；内容冲突则停止该类汇总，提示纠正。
- 评审支持采纳、修改人工意见、驳回、待核查；原建议不被覆盖。数值/版本/范围修正须返回输入重算。
- PDF 报告含可读证据片段、页/行号、输入哈希与未决事项；CSV 采用 UTF-8 BOM 并防公式解释。已导出报告不随后续输入或评审变化而改写。

## 6. 代码结构

```text
app.py                 HTTP 接口、输入版本、运行编排、评审及导出
model.py               DeepSeek 图像输入与 JSON 提取、重试/取消检查
parsers.py             文档解析、来源位置、表头映射、本地标注解析
engine.py              Decimal 比较、证据校验、BR01–BR06 业务规则
storage.py             SQLite 对象存储、审计事件、重启恢复
reports.py             PDF 报告、CSV 处理清单
static/                无远程 CDN 依赖的浏览器界面
samples/               模拟输入，含改为 5.0 mm 的扰动图纸
tests/                 规则、接口与模型错误路径回归
tools/create_samples.py 可复现样例生成器
assets/                开源中文字体与 OFL 许可证
docs/                  测试说明、实测记录、版本范围说明
```

数据库及文件默认存于 `data/`，包含 `app.sqlite3`、`files/` 和 `reports/`。备份前关闭服务并复制整个 `data/` 目录（含可能存在的 SQLite WAL 文件）。设置进程环境变量 `ZBL_DATA_DIR` 可使用独立数据目录。默认不自动清除历史资料；“移出”只影响当前输入。

## 7. 测试与实际完成范围

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

测试使用独立临时数据库，并强制清空测试进程的 API Key，**不会调用收费接口或改动个人数据**。测试替身仅用于重试、鉴权和迟延响应路径，程序中没有测试结果回退逻辑。

详见 `docs/测试与实测记录.md`、`docs/版本范围说明.md`。已完成核心闭环，但并未声称完整实现原 PRD 所有 P0，也未完成 20 组独立统计验收。请勿把回归通过数或单一案例耗时宣传为通用识别准确率或企业收益。

## 8. 常见问题

- **模型未配置/401**：在本机 `.env` 配置有效密钥；不要在前端填入密钥。检查环境变量是否覆盖 `.env`。
- **待补充：引用无法核验**：查看原图，在“变更对比 → 核查/修正字段”填写核验后的 JSON 及理由，重跑。
- **字段映射不通过**：检查表头是否覆盖角色必需字段；业务数值错误请修改源文件并明确替换。
- **版本冲突/相同记录编号不同内容**：回到资料核对；修正文件后重新分析，不编辑结论文本绕过计算。
- **端口被占用**：先关闭已运行实例，或设置 `ZBL_PORT` 为其他端口后运行 `app.py`。
- **首次 PDF 导出稍慢**：程序载入并嵌入中文字体；导出快照生成后可重复下载，不会重新调用模型。

## 第三方资源

中文 PDF 字体为 LXGW WenKai，按 SIL Open Font License 1.1 随附原始字体及许可证（`assets/OFL.txt`）。Python 依赖按各自许可证分发；源码包仅声明依赖，不打包 Python 解释器、浏览器或模型权重。界面未使用外部图片素材。模拟图纸由 `tools/create_samples.py` 生成。
