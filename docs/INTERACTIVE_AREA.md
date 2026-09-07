# 交互区显示库：`courser`

`courser` 是 TS-Courser 网站在交互式 Python 题目中提供的教学库，不是 Python 标准库；显示功能依赖网站运行器。它用来把程序运行时的数据快照送到页面的交互区。

在网站运行代码时，系统会先将模块预载入 Pyodide 的 Python 环境；随后学生代码照常导入：

```python
from courser import display, display_map, define_symbol
```

每次点击“运行”都会开始一套新的显示标签和符号定义。程序已经显示过的数据也不会因为后来修改变量或重新定义符号而改变。

## `display(value, label=None)`

显示一个值的快照。`value` 可以是 `int`、有限 `float`、`str`、`bool`、`None`，或最多两层嵌套的列表；不规则列表也可以。

```python
score = 0
display(score, "得分")

items = ["钥匙", True, [1, 2], []]
display(items, "背包")
items[0] = "已经改变"       # 已发送的“背包”快照不会改变

display("下一步：向北走", "提示")  # 更新同一个“提示”区域
```

省略 `label` 时使用默认显示区域。相同标签会更新同一个区域，不同标签彼此独立。交互区支持地图/数据视图切换、显示单元格索引、点击单元格查看与高亮，以及标签显示；这个库不提供精灵、绘图、动画或其他图形 API。

## `define_symbol(value, symbol)` 与 `display_map(grid)`

先用 `define_symbol` 为你自己的标量值定义地图文字，再用 `display_map` 显示矩形二维列表。库不会预先规定“墙必须是 1”或任何其他值。

```python
WALL = 1
ROAD = 0
EXIT = 2
PLAYER = "P"

define_symbol(WALL, "🧱")
define_symbol(ROAD, "·")
define_symbol(EXIT, "🏁")
define_symbol(PLAYER, "🙂")

board = [
    [1, 1, 1, 1],
    [1, 0, "P", 1],
    [1, 0, 2, 1],
    [1, 1, 1, 1],
]
display_map(board)
```

符号只会影响**之后**调用的 `display_map`。每一次地图显示都会使用当时的全部符号定义；`define_symbol` 本身不会立即显示地图。未定义的值会保留原始值的文本形式。值的类型也有区别：`1`、`True` 和 `"1"` 可以分别定义不同符号。

地图必须是非空、矩形的二维 `list`，每个格子都必须是受支持的标量。地图最多 100 行、100 列，且最多 2500 个格子。

## 输入与回合制小游戏

`input()` 会在页面内嵌输入框中暂停程序，等待玩家输入；按 Enter 或 Send 后继续执行。迷宫等回合制程序还可以展开可选的 W/A/S/D 按钮直接发送方向。选择 Cancel input 会让 `input()` 抛出 `EOFError`。因此先显示当前局面，再调用 `input()`，就可以写回合制游戏。完整示例见 [interactive_maze.py](examples/interactive_maze.py)。

```python
display_map(board)
command = input("输入 w/a/s/d，q 退出：")
```

## 限制和错误

这些限制会在普通运行和自动评测中验证。自动评测模式不会向网页发送显示事件。

| 项目 | 限制 |
| --- | --- |
| 单次 `display` 或 `display_map` 的标量格数 | 最多 2500 |
| `display` 列表嵌套 | 最多两层 |
| 任意输入列表的直接元素数 | 最多 2500 |
| 显示区域 | 最多 20 个（默认区域也算一个） |
| 符号定义 | 最多 100 个 |
| 普通字符串 | 最长 500 个字符 |
| 标签 | 最长 60 个字符 |
| 符号文本 | 1–32 个字符 |

循环列表、元组/字典/对象等不支持的值、`nan` 和 `inf` 会抛出清晰的 `TypeError` 或 `ValueError`。所有三个公开函数都返回 `None`。

## 面向课程开发的加载说明

前端应在 Pyodide 初始化时从 `/static/python/courser.py` 读取源码，写入动态取得的 `sysconfig.get_path('purelib')` 目录。这样学生可以使用标准的 `from courser import ...`。在每次学生运行或每个评测用例之前，应重新导入模块或移除模块缓存，并调用私有的 `_configure(emit, enabled)` 来清空标签和符号状态；`emit` 接收一条 JSON 字符串，评测时 `enabled=False`。

Pyodide 的官方资料：[加载自定义 Python 代码](https://pyodide.org/en/0.29.4/usage/loading-custom-python-code.html) 和 [JavaScript API](https://pyodide.org/en/0.29.4/usage/api/js-api.html)。
