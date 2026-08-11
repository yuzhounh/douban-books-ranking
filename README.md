# 豆瓣读书综合排行榜

从豆瓣读书公开的 Top 250、标签、豆列与丛书列表页采集书籍信息，按豆瓣 subject ID 去重，并以评分和评价人数计算综合排名。

> 使用前请确认你的使用方式符合豆瓣网站条款与当地法律。本项目只处理公开列表页，不绕过验证码或访问控制；遇到风控提示时应停止请求。

## 在线排行榜

在线展示页面：<https://yuzhounh.github.io/douban-books-ranking/>

页面首先提供“全部书籍”全库搜索，可按书名、豆瓣 ID、最低评分和最低评价人数筛选；其后按“标签、豆列、丛书、Top 250”四类来源展示综合排行榜。各来源支持名称搜索和分页浏览，点击“豆瓣”可打开对应书籍页面。

## 当前数据规模

最近一次生成于 **2026-08-11**：

- 去重书籍：**338,820 本**
- 标签：**626 个**，仅保留不少于 100 本书的标签
- 豆列：**393 个**，排除历史抓取失败及少于 10 本书的豆列
- 丛书：**55 个**
- 豆瓣读书 Top 250：**250 本**

豆列和丛书按所含书籍数量从多到少排列。每个来源内部均按综合评分降序排列。

## 综合评分

```text
综合评分 = (评分 - 2.5) × ln(评价人数)
```

其中 `ln` 是自然对数。公式同时考虑书籍评分和评价样本量，并通过对数降低超高评价人数的边际影响；无评分记录排在最后。

## 数据内容

每条书籍记录包含：

| 字段 | 含义 |
|---|---|
| `id` | 豆瓣书籍 subject ID |
| `title` | 书名 |
| `rating` | 豆瓣评分 |
| `rating_count` | 评价人数 |
| `url` | 豆瓣书籍页面链接 |

网站目录位于 `data/catalog.json`，各来源按每页 100 本拆分为独立 JSON 文件，浏览器只加载当前页面所需的数据。“全部书籍”首次打开时按需加载紧凑索引 `data/all-books.json`，并在 Web Worker 中执行全库搜索与阈值筛选，避免阻塞页面交互。

## 项目结构

```text
.
├─ src/douban_books/    # 爬虫、解析器、存储、排名、分析及发布代码
├─ tests/               # 自动化测试与脱敏 HTML 夹具
├─ sources/             # 最终保留的标签、豆列和丛书来源清单
├─ analysis/            # 最终统计摘要与分析报告
├─ assets/              # 展示页面的 JavaScript 与 CSS
├─ data/                # 按来源和分页拆分的公开书籍数据
├─ index.html           # GitHub Pages 入口
└─ pyproject.toml       # Python 包与依赖配置
```

`sources/tags.txt`、`sources/doulists.txt` 和 `sources/series.txt` 是清理后的抓取入口：标签不少于 100 本，豆列不少于 10 本且排除了历史抓取失败项。Top 250 使用固定入口，无需单独的 ID 清单。

SQLite 工作数据库、HTML 缓存、运行日志和备份不进入仓库；网站实际展示的书籍记录已按来源保存在 `data/` 中。

## 安装与抓取

需要 Python 3.10 或更高版本：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

douban-books crawl `
  --tag-file sources/tags.txt `
  --doulist-file sources/doulists.txt `
  --series-file sources/series.txt `
  --top250
```

默认使用 `data/douban_books.sqlite3` 保存进度，成功页面可断点续爬。请控制请求频率；遇到 HTTP 403、418、验证码或异常请求提示时应停止。

## 分析与测试

```powershell
douban-books analyze --out-dir analysis --top 5000
python -m pytest
```

分析实现位于 `src/douban_books/analysis.py` 和 `ranking.py`。`analysis/summary.json` 提供机器可读统计，`analysis/report.md` 提供简要报告。

## 更新与发布

在主项目完成抓取后重新生成并发布：

```powershell
python -m douban_books finalize
python -m douban_books publish-pages `
  --site-dir data/github-pages `
  --checkout-dir data/pages-repository `
  --repository https://github.com/yuzhounh/douban-books-ranking.git
```

发布命令只更新本仓库，不会修改 `yuzhounh.github.io` 仓库。

## 说明

- 数据来源于公开页面，仅供研究、数据分析和个人阅读参考。
- 评分、评价人数及榜单内容会随豆瓣页面变化，本站不是豆瓣官方产品。
- 项目不包含验证码破解、账号池、登录 Cookie 获取、代理轮换或其他风控规避功能。
