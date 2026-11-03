# StudentRiskGuard GitHub 仓库提交清单

- 目的：说明哪些文件放进 GitHub，哪些文件只保留在本机
- 原则：GitHub 管理项目源代码和协作文档，不保存密钥、原始问卷和个人金融明细

## 1. 应该提交什么

以下文件属于项目资产，建议提交：

```text
AGENTS.md
.gitignore
StudentRiskGuard商业计划书.docx
contracts/
docs/
src/                  # 实现后提交
tests/                # 实现后提交
app.py                # 实现后提交
pyproject.toml
requirements.txt
README.md
Dockerfile
.env.example
```

### 1.1 文档

- `docs/00` 到 `docs/17` 的开发方案、排期、问卷、接口和验收文档。
- `AGENTS.md`：队友 Codex 的项目规则。
- `contracts/`：请求、结果、Agent、样本和评分卡配置。
- `docs/15_问卷正文_发搭档审核.md/.txt`：问卷正文，可以提交。
- 最终需要提交的商业计划书、需求文档和原型说明。

### 1.2 源代码

实现后提交：

- `app.py`
- `src/riskguard/`
- `tests/`
- `requirements.txt`
- `pyproject.toml`
- `Dockerfile`
- `.env.example`
- `README.md`

### 1.3 合成数据和演示样本

可以提交：

- `contracts/demo_cases.json`
- `src/riskguard/data/synthetic.py`
- 小体积、固定随机种子的合成样本

不要提交：

- 真实用户账单。
- 真实问卷明细。
- 可反推个人身份的原始回答。

## 2. 不要提交什么

以下内容保留在本机，并由 `.gitignore` 排除：

```text
.env
.env.*
.streamlit/secrets.toml
*.pem
*.key
data/raw/
data/private/
survey/raw/
survey/private/
*_raw.csv
*_raw.xlsx
*_raw.xls
*.db
*.sqlite
*.sqlite3
__pycache__/
.pytest_cache/
.venv/
logs/
*.log
renders/
qa_output/
tmp/
~$*.docx
```

### 2.1 尤其不能提交

- DeepSeek API Key。
- HuggingFace Token。
- 手机号、姓名、学号、身份证、银行卡。
- 问卷星原始答卷。
- 真实账单文件。
- 浏览器导出的私密数据。
- 日志中的金额和月供明细。

## 3. 自动生成文件怎么处理

| 文件类型 | 是否提交 | 说明 |
|---|---|---|
| Markdown 开发文档 | 提交 | 队友 Codex 需要读取 |
| 问卷题目 CSV | 提交 | 机器可读，可版本管理 |
| 字段映射 CSV | 提交 | 统计和计算机对齐使用 |
| JSON Schema | 提交 | 接口和 Agent 契约 |
| 演示样本 JSON | 提交 | 全部是合成数据 |
| 最终 DOCX/PDF | 视情况提交 | 小体积终稿可放 `deliverables/` |
| 问卷星原始 Excel | 不提交 | 可能包含个人回答 |
| 临时渲染图片和 PDF | 不提交 | 放 `renders/`，已忽略 |
| `.env` | 不提交 | 只提交 `.env.example` |
| 日志 | 不提交 | 只保留匿名技术日志策略 |
| `__pycache__`、pytest 缓存 | 不提交 | 自动生成文件 |

## 4. 是否直接上传整个项目文件夹

正确做法：

1. 把 `E:\code_project\RiskAgent` 作为 Git 仓库根目录。
2. 进入这个目录执行 `git init`。
3. 让 `.gitignore` 生效。
4. 用 `git add .` 添加已被 Git 跟踪且未被忽略的文件。
5. 提交并推送到 GitHub。

不要提交：

- `E:\code_project` 整个父目录。
- 微信缓存目录。
- 问卷星原始文件所在目录。
- 与项目无关的其他项目。

## 5. 初始化仓库命令

```powershell
cd E:\code_project\RiskAgent
git init
git add .
git commit -m "chore: initialize StudentRiskGuard project"
git branch -M main
git remote add origin <你的GitHub仓库地址>
git push -u origin main
```

执行 `git add .` 后先运行：

```powershell
git status
```

确认列表中没有 `.env`、原始问卷、日志和缓存，再提交。

## 6. 推荐仓库结构

```text
RiskAgent/
  AGENTS.md
  README.md
  .gitignore
  StudentRiskGuard商业计划书.docx
  app.py
  pyproject.toml
  requirements.txt
  Dockerfile
  .env.example
  contracts/
  docs/
  src/
    riskguard/
      models/
      core/
      data/
      services/
      tools/
      agent/
      api/
      ui/
  tests/
  deliverables/        # 只放最终小体积提交件
```

## 7. 问卷数据单独管理

建议把问卷原始数据放在仓库外，例如：

```text
E:\code_project\RiskAgent_private\survey\
```

统计同学分析后，只提交：

- 匿名汇总结果。
- 描述统计图。
- 清洗规则。
- 冻结后的评分参数。
- 样本量和局限说明。

## 8. 每次提交前检查

- [ ] `git status` 没有 `.env`。
- [ ] 没有 API Key。
- [ ] 没有问卷星原始答卷。
- [ ] 没有真实账单和身份字段。
- [ ] 没有 `__pycache__` 和日志。
- [ ] `contracts/` 与最新文档一致。
- [ ] 演示样本全部是合成数据。
- [ ] README 启动步骤可执行。
