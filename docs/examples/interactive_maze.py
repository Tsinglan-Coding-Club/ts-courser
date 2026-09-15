"""A small turn-based maze for the TS-Courser interactive area."""

from courser import display, display_map, define_symbol


WALL = 1
PATH = 0
EXIT = 2
PLAYER = 3

define_symbol(WALL, "🧱")
define_symbol(PATH, "·")
define_symbol(EXIT, "🏁")
define_symbol(PLAYER, "🙂")

maze = [
    [1, 1, 1, 1, 1, 1, 1],
    [1, 0, 0, 1, 0, 2, 1],
    [1, 1, 0, 1, 0, 1, 1],
    [1, 0, 0, 0, 0, 0, 1],
    [1, 1, 1, 1, 1, 1, 1],
]

player_row = 1
player_column = 1
exit_row = 1
exit_column = 5
message = "到出口去。输入 w、a、s、d 移动，q 退出。"

while True:
    board = []
    for row in maze:
        board.append(row[:])
    board[player_row][player_column] = PLAYER

    display(message, "提示")
    display_map(board)
    command = input("w/a/s/d，q 退出：").lower()

    if command == "q":
        display("游戏结束。", "提示")
        break
    if command == "w":
        next_row = player_row - 1
        next_column = player_column
    elif command == "s":
        next_row = player_row + 1
        next_column = player_column
    elif command == "a":
        next_row = player_row
        next_column = player_column - 1
    elif command == "d":
        next_row = player_row
        next_column = player_column + 1
    else:
        message = "请输入 w、a、s、d 或 q。"
        continue

    if maze[next_row][next_column] == WALL:
        message = "那里是墙，不能通过。"
        continue

    player_row = next_row
    player_column = next_column
    if player_row == exit_row and player_column == exit_column:
        board = []
        for row in maze:
            board.append(row[:])
        board[player_row][player_column] = PLAYER
        display("你到达出口，赢了！", "提示")
        display_map(board)
        break
    message = "继续前进。"
