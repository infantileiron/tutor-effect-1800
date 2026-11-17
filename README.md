# 课程辅导效果检验 · Tutor Effect

知行职教教研组用真实的两组成绩评估晚间小组辅导效果，贯通成绩复核、辅导方案、后台统计检验、结论签核和结果导出。

## 业务场景
知行职教有城东、城西、滨江、高新 4 个教学点。原流程由教学点导出成绩表，分析员复制进工作簿计算，再将截图发给负责人。三类痛点是：排除缺考时容易丢失口径、方案与结果脱节、签核结论没有当时的样本证据。上游是教学点期末成绩；本应用替代手工核对与计算；下游由教研负责人决定是否扩大辅导试点。

五个业务模块：**成绩样本**支持筛选、录入和修订；**辅导分组**登记研究范围和排除规则；**检验工作台**提交后台任务并查看失败原因与历史结果；**补测抽样**对缺考者按教学点和原分组抽取补测名额、登记回应并查看样本去向；**教研结论**起草解释、负责人签核并下载包括原始样本和补测聚合快照的 JSON 报告。业务数据均在 PostgreSQL 中持久化，统计由 Python worker 计算。

## 启动
```sh
cp .env.example .env
docker compose up -d --build
# 可选：手动幂等 seed
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18202 。API http://localhost:19202/docs 。数据库端口 17702。停止并清空演示数据：`docker compose down -v --remove-orphans`。Compose 顶层 name 保证中文父目录也能运行。

|角色|账号|密码|权限|
|---|---|---|---|
|教研负责人 admin|admin@demo.local|Demo123!|全部编辑、统计、结论签核发布、审计|
|教研分析员 analyst|analyst@demo.local|Demo123!|成绩/方案编辑、检验、未签核结论起草；不能签核或改已签核结论|
|教学点观察员 viewer|viewer@demo.local|Demo123!|只读台账、方案、报告及导出；不能发起计算|

JWT 有效期 8 小时；角色由服务器读取数据库，不信任客户端显示。密码使用随机盐 PBKDF2-SHA256 180000 次，登录不保存明文密码。

## 一天的工作剧本
1. 08:50 观察员打开 `ZX-2026-001` 学员记录，核对缺考标记。
2. 09:00 分析员查看 160 名学员，按城东教学点筛选。
3. 09:10 录入 `ZX-2026-161`，学员161，城东，小组辅导组，82.5 分。
4. 09:20 将缺考学员标记为缺考并清空成绩，避免把零分当缺失。
5. 09:30 新建 `2026秋季 · 城东晚间辅导` 方案，选城东并排除缺考。
6. 09:40 提交后台检验；界面自动更新排队、完成或失败状态。
7. 10:00 查看两组均分、95% 区间、p 值、Cohen d 和排除数，起草后续随机试验建议。
8. 10:10 负责人签核结论；分析员不能修改已签核报告。
9. 10:20 观察员下载 `tutor-effect-report-<id>.json`，复核当时样本快照和 SHA-256。
10. 10:30 分析员在补测抽样页为方案发起补测，系统封存抽样设计并抽出每层名额；发出名单后登记愿意返校、拒绝或失联，未回应者不补抽。

## 算法与口径
输入是方案教学点内两组 0–100 分成绩。空成绩永远排除；开启排除缺考时再排除 absent=true 的成绩。显示总选中数和排除数。有效样本每组至少 2 条；两组方差都为零时任务失败且保留可读原因。

以干预组减对照组定义 Δ。Welch t = Δ / sqrt(s1²/n1+s0²/n0)，自由度使用 Welch-Satterthwaite 公式；双侧 p 值和 95% 区间通过 SciPy t 分布计算。Cohen d 使用两组自由度加权 pooled 标准差，描述效应大小，与 Welch 方差假设相互独立。显著性 α 固定为 0.05。观察性分组不能直接做因果断言。

### 补测抽样与总体均分
缺考者只补测愿意返校的人会高估辅导效果，因此补测名额必须来自概率抽样。发起补测时冻结“原应考名册”（当前成绩与其缺考标记），按 **教学点 × 原分组** 分层，在每层缺考名册内无放回抽取 min(每层名额, N_h) 人；入选概率 π = n_h / N_h 在抽取前写入设计，随设计校验码、随机种子和名册 SHA-256 一起封存。每个方案只有一份抽样设计：重复提交返回原设计，重复执行沿用原名单，唯一约束保证同一学生不会二次入选；抽样后的名册修订和并发补分都不会改变 π。名单状态为待抽取 → 待发出 → 已发出，登记回应前必须先发出。拒绝、失联与未回应只追加记录，不补抽新人。

登记回应时须提供 0–100 的补测分（仅愿意返校时）；服务端用 `response_version` 做乐观锁，旧版本提交返回 409，所有回应按时间留痕，样本页可查看层、π、抽取序号、冻结名册记录和完整回应历史。

检验报告的补测聚合以冻结名册为总体：非缺考且有成绩者按实际成绩计入，缺考者按分层概率样本估计。点估计对每层使用回应调整权重 N_h / r_h（即该层缺考总分的估计 = N_h × 回应者均分），再与已观测成绩合并为组均分；**假设同一层内回应与否与补测成绩无关（MAR）**。当某层没有任何回应时点估计不可识别，改报 0–100 分下两个组均分的识别区间及其差（受 −100…100 截断），只要区间跨 0 就明说“效果无法识别”；同时并列展示“仅用回应者”的有偏估计，提醒它会高估效果。补测者始终只代表缺考总体，绝不被当作全体学员。报告的补测部分在受理时封存：之后新增或修订的回应不会改写已受理报告，导出 JSON 同时含统计量、原始样本快照和受理时的补测快照。

seed 使用 Random(20261115)：160 名学员，4 教学点、各 80 人两组、7 条缺考记录；初始方案为 `2026秋季 · 晚间小组辅导`，初始报告为便于演示的真实计算结果，并附带一份固定种子、每层 2 名、已发出且含愿意返校/拒绝/失联回应的补测抽样。seed 以 email/code/title 自然键查重，已存在对象不更新，重跑不覆盖用户修改。报告保存计算样本快照与校验码；后续成绩修订不会改旧报告。

## 技术与结构
|层|技术|
|---|---|
|前端|原生 HTML/CSS/ES Modules、Nginx 1.27，无构建依赖|
|后端|Python 3.11、FastAPI 0.115.6、SQLAlchemy 2.0.36|
|统计|SciPy 1.14.1|
|数据与队列|PostgreSQL 16、Redis 7，独立 Python worker|
|认证|PyJWT 2.10.1、PBKDF2|

`frontend/src/api` 负责请求，`stores` 管业务状态，`pages` 分五页，`components/common` 复用结果、表格、状态和通知，`hooks` 封装表单/轮询，`utils` 做转义/下载。`backend/src/models` 定义表，`schemas` 验证，`services` 处理业务与算法，`routes` 提供接口，`controllers` 序列化，`middlewares` 处理审计和全局错误。`backend/migrations/001_initial.sql` 是初始结构，`002_supplement.sql` 为既有库补加补测表与报告快照列；启动使用 metadata.create_all，后续字段迁移需人工管理。

共享枚举位置：角色 ROLES、分组 GROUPS、报告状态 REPORT_STATUSES、抽名单状态 DRAW_STATUSES、回应 OUTCOMES 在 `backend/src/constants/enums.py`；前端对应 `frontend/src/constants/enums.js` 的 ROLES、GROUPS、STATUS。API输入的 group 枚举同时在 `backend/src/schemas/business.py` 校验。

## Docker 与环境变量
恰好五服务：frontend/backend/worker/db/redis，各有健康检查。backend 和 worker 依赖健康 DB/Redis，frontend 依赖 backend；worker 依赖 backend 初始化完成。数据库、Redis AOF、报告产物预留共享卷分别命名。worker 真正从 Redis 唤醒并处理数据库待执行任务，每 2 秒更新心跳。Redis 任务通知丢失仍会扫描数据库待执行任务。计算结果权威存于数据库，shared reports 卷供未来文件归档；当前 JSON 按快照直接导出。

`.env.example` 列出 COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、POSTGRES_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET（默认 10.253.103.0/24）。所有变量均可覆盖；默认是本地演示配置，外部部署前需更换密码和 JWT_SECRET。`.env` 已忽略。每次最多允许 10 个待执行任务，HTTP 429 提示等待。

## 本地开发
后端在 Python3.11 虚拟环境运行 `pip install -r backend/requirements.txt`，设置 DATABASE_URL、REDIS_URL、JWT_SECRET，进入 backend 后运行 `uvicorn src.main:app --reload` 和另一个终端 `python -m src.worker`。前端无打包步骤，可直接由 Nginx 提供静态文件并代理 /api/。

## 已知范围
不含 CSV 批量导入、随机分组器或多重比较校正；成绩可逐条录入/修订。补测抽样没有基于成绩的分层、无多重插补与设计效应方差；点估计依赖 MAR，样本很小时识别区间可能很宽。教学点为自由文本，前端方案选项来自现有成绩。初始报告为同步真实计算的演示快照，新提交报告全部走异步 worker。外网字体不可用时使用本地 serif 回退。进程中断在 running 状态的任务需管理员在数据库重置为 queued；当前小型版本未提供任务取消/自动回收。审计列表只给管理员，最多最近 100 条。

License: MIT（见 LICENSE）。真实验收证据在批次根 `test-artifacts/gb-3103/`，源码目录不含截图或测试报告。
