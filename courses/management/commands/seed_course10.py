import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from courses.models import Course, Episode, Section
from progress.models import (
    CodeSubmission,
    CourseEnrollment,
    EpisodeReadStatus,
    QuizSubmission,
    UserProgress,
)


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

MATERIAL_1_1 = """# 第一个 Python 程序

## 输出

使用 `print()` 函数把内容显示到控制台：

```python
print("Hello, world!")
print(2024)
```

`print()` 也可以一次输出多个值，用逗号分隔：

```python
name = "Alice"
print("Hi", name)
```

## 注释

注释不会被 Python 执行，用于解释代码：

```python
# 这是单行注释
print("这一行会被执行")  # 行尾也可以写注释
```
"""

MATERIAL_1_2 = """# 变量与数据类型

## 变量

变量用来保存数据，使用 `=` 赋值：

```python
age = 18
name = "Tom"
pi = 3.14
is_student = True
```

## 常见数据类型

- `int`：整数，如 `18`
- `float`：小数，如 `3.14`
- `str`：字符串，如 `"Tom"`
- `bool`：布尔值，只有 `True` 和 `False`

使用 `type()` 查看某个值的数据类型：

```python
print(type(age))   # <class 'int'>
print(type(name))  # <class 'str'>
```
"""

QUIZ_1 = """## 下列哪一个是 Python 中用于向控制台输出的函数？
>+ print()
> echo()
> console.log()
> printf()

## 以下哪些是合法的 Python 变量名？（多选）
>* user_name
>* _count
> 2nd_value
> class
>* totalScore

## 请按“编写程序的一般步骤”排序（先到后）
>3 编写代码
>1 分析问题
>4 测试运行
>2 设计算法

## Python 中使用哪个符号给变量赋值？
>+ =
> ==
> =>
> <-
"""

MATERIAL_2 = """# 读取输入与算术运算

## input() 读取输入

`input()` 读取用户输入，默认返回字符串：

```python
line = input()
print("你输入了:", line)
```

要参与数学运算，通常先把字符串转换成数字：

```python
n = int(input())  # 转成整数
```

## 算术运算符

- `+` 加
- `-` 减
- `*` 乘
- `/` 除，结果为浮点数
- `//` 整除
- `%` 取余
- `**` 幂运算
"""

CODE_1_INFO = """# 两数之和

读取两个整数，输出它们的和。

## 输入格式

共两行，每行一个整数。

## 输出格式

一个整数，表示两数之和。

## 示例

输入：

```
1
2
```

输出：

```
3
```
"""

CODE_1_REFERENCE = """## 读取输入
```python
s = input()        # 读取一行字符串
n = int(input())   # 读取一行并转换成整数
```
- `input()` 总是返回字符串
- 两个整数分两行输入时，调用两次 `input()`

## 输出
```python
print(value)
print(a + b)
```
- `print()` 会自动换行
- 可以打印表达式的结果
"""

QUIZ_2 = """## input() 函数读取的数据默认是什么类型？
>+ 字符串
> 整数
> 浮点数
> 布尔值

## 表达式 7 // 2 的结果是？
>+ 3
> 3.5
> 2
> 4

## 请用自己的话解释 int() 函数的作用。
>= 将字符串或数字转换为整数类型。
"""

MATERIAL_3_1 = """# 条件判断 if/else

使用 `if`、`elif`、`else` 根据条件执行不同的代码：

```python
score = int(input())

if score >= 90:
    print("A")
elif score >= 60:
    print("B")
else:
    print("C")
```

## 比较运算符

- `>` 大于
- `<` 小于
- `>=` 大于等于
- `<=` 小于等于
- `==` 等于
- `!=` 不等于
"""

MATERIAL_3_2 = """# 循环 for/while

## for 循环

`for` 用来遍历一个序列：

```python
for i in range(1, 4):
    print(i)

# 输出 1、2、3
```

## while 循环

`while` 在条件成立时重复执行：

```python
n = 3
while n > 0:
    print(n)
    n = n - 1
```

`break` 立即结束循环，`continue` 跳过本次循环的剩余部分。
"""

CODE_2_INFO = """# 判断奇偶

读取一个整数，判断它是偶数还是奇数。

## 输出格式

- 如果是偶数，输出 `Even`
- 如果是奇数，输出 `Odd`

## 示例

输入 `4`，输出 `Even`。

输入 `7`，输出 `Odd`。
"""

CODE_2_REFERENCE = """## 取余运算符
```python
n % 2
```
- 偶数除以 2 的余数是 0
- 奇数除以 2 的余数是 1

## 条件表达式
```python
"Even" if n % 2 == 0 else "Odd"
```
- 条件成立时取 `if` 前面的值
- 条件不成立时取 `else` 后面的值
"""

QUIZ_3 = """## if 后面的条件表达式的结果应该是什么类型？
>+ 布尔值
> 整数
> 字符串
> 列表

## 以下哪些循环会输出 1、2、3？（多选）
>* for i in range(1, 4): print(i)
>* for i in [1, 2, 3]: print(i)
> for i in range(3): print(i + 2)
>* for i in range(3): print(i + 1)

## 请按执行顺序排列以下语句（先到后）
>2 a = a + 2
>1 a = 1
>3 print(a)

## 哪个关键字用于立即跳出当前循环？
>+ break
> continue
> return
> exit
"""


SECTIONS = [
    {
        "title": "Unit 1: Python 基础语法",
        "episodes": [
            {"title": "第一个程序：输出与注释", "type": "material", "info": MATERIAL_1_1},
            {"title": "变量与数据类型", "type": "material", "info": MATERIAL_1_2},
            {"title": "第一单元：语法自测", "type": "quiz", "info": QUIZ_1, "policy": "immediate"},
        ],
    },
    {
        "title": "Unit 2: 输入与运算",
        "episodes": [
            {"title": "读取输入与算术运算", "type": "material", "info": MATERIAL_2},
            {
                "title": "两数之和",
                "type": "code",
                "info": CODE_1_INFO,
                "reference": CODE_1_REFERENCE,
                "testcases": [
                    {"input": "1\n2", "expected": "3"},
                    {"input": "5\n6", "expected": "11"},
                    {"input": "132\n23", "expected": "155"},
                ],
            },
            {"title": "第二单元：运算测验", "type": "quiz", "info": QUIZ_2, "policy": "inherit"},
        ],
    },
    {
        "title": "Unit 3: 条件与循环",
        "episodes": [
            {"title": "条件判断 if/else", "type": "material", "info": MATERIAL_3_1},
            {"title": "循环 for/while", "type": "material", "info": MATERIAL_3_2},
            {
                "title": "判断奇偶",
                "type": "code",
                "info": CODE_2_INFO,
                "reference": CODE_2_REFERENCE,
                "testcases": [
                    {"input": "4", "expected": "Even"},
                    {"input": "7", "expected": "Odd"},
                    {"input": "0", "expected": "Even"},
                ],
            },
            {"title": "第三单元：综合测验", "type": "quiz", "info": QUIZ_3, "policy": "immediate"},
        ],
    },
]


# username -> (display_name, email, read_count, enrolled_days_ago)
STUDENTS = [
    ("Charles", "Charles Wang", "charles@charles.com", 0, 40),
    ("Alice", "Alice Li", "alice@example.com", 1, 36),
    ("Bob", "Bob Zhang", "bob@example.com", 2, 33),
    ("Carol", "Carol Chen", "carol@example.com", 3, 29),
    ("David", "David Liu", "david@example.com", 4, 25),
    ("student", "Student Lee", "student@student.com", 5, 21),
    ("Emma", "Emma Zhao", "emma@example.com", 6, 17),
    ("Frank", "Frank Sun", "frank@example.com", 7, 13),
    ("Grace", "Grace Wu", "grace@example.com", 8, 9),
    ("Henry", "Henry Xu", "henry@example.com", 8, 7),
    ("Ivy", "Ivy Zhou", "ivy@example.com", 9, 5),
    ("Jack", "Jack Ma", "jack@example.com", 9, 4),
    ("Kate", "Kate Lin", "kate@example.com", 10, 2),
    ("Leo", "Leo Huang", "leo@example.com", 10, 1),
]


class Command(BaseCommand):
    help = "Seed course 10 with meaningful units/episodes and varied student progress."

    def handle(self, *args, **options):
        try:
            course = Course.objects.get(pk=10)
        except Course.DoesNotExist as exc:
            raise CommandError("Course with pk=10 does not exist.") from exc

        self.stdout.write(self.style.MIGRATE_HEADING(f"Seeding course 10: {course.title}"))

        self._reset_course(course)
        episodes = self._create_content(course)
        students = self._seed_students(course, episodes)
        self._seed_submissions(course, students, episodes)

        self.stdout.write(self.style.SUCCESS("Course 10 seed completed."))

    def _reset_course(self, course):
        course.description = (
            "Python 编程入门：从输出、输入、算术运算，到条件判断与循环。"
        )
        course.save(update_fields=["description"])

        # Deleting sections cascades to episodes, read statuses, and submissions.
        Section.objects.filter(course=course).delete()
        UserProgress.objects.filter(course=course).delete()
        CourseEnrollment.objects.filter(course=course).delete()

    def _create_content(self, course):
        episodes = []

        for section_index, section_spec in enumerate(SECTIONS):
            section = Section.objects.create(
                course=course,
                title=section_spec["title"],
                order=section_index,
            )

            for order, spec in enumerate(section_spec["episodes"]):
                episode = Episode(
                    section=section,
                    title=spec["title"],
                    type=spec["type"],
                    order=order,
                    info_page_content=spec.get("info", ""),
                )

                if spec["type"] == "quiz":
                    episode.quiz_release_policy = spec.get("policy", "inherit")
                    episode.quiz_require_all = True
                elif spec["type"] == "code":
                    episode.code_oj_enabled = True
                    episode.code_oj_testcases = json.dumps(spec.get("testcases", []))
                    episode.reference_sheet_content = spec.get("reference", "")

                episode.save()
                episodes.append(episode)

        return episodes

    def _seed_students(self, course, episodes):
        students = {}
        total = len(episodes)

        for username, display_name, email, read_count, days_ago in STUDENTS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"email": email, "role": "student", "is_email_verified": True},
            )

            user.role = "student"
            user.is_email_verified = True
            user.display_name = display_name
            user.save()

            if created:
                user.set_password("password123")
                user.save(update_fields=["password"])

            enrollment, _ = CourseEnrollment.objects.get_or_create(
                user=user, course=course
            )
            CourseEnrollment.objects.filter(pk=enrollment.pk).update(
                enrolled_at=timezone.now() - timedelta(days=days_ago)
            )

            for episode in episodes[:read_count]:
                EpisodeReadStatus.objects.update_or_create(
                    user=user,
                    episode=episode,
                    defaults={"is_read": True},
                )

            current_episode = episodes[read_count] if read_count < total else episodes[-1]
            UserProgress.objects.update_or_create(
                user=user,
                course=course,
                defaults={"current_episode": current_episode},
            )

            students[username] = user

        return students

    def _seed_submissions(self, course, students, episodes):
        ep = {e.title: e for e in episodes}

        self._add_quiz(
            students["Carol"],
            ep["第一单元：语法自测"],
            {"questions": [
                {"type": "mcq", "selectedIndex": 0},
                {"type": "mrq", "selectedIds": [0, 1, 4]},
                {"type": "srt", "selectedIds": [2, 0, 3, 1]},
                {"type": "mcq", "selectedIndex": 0},
            ]},
            released=True,
        )
        self._add_quiz(
            students["David"],
            ep["第一单元：语法自测"],
            {"questions": [
                {"type": "mcq", "selectedIndex": 0},
                {"type": "mrq", "selectedIds": [0, 1]},
                {"type": "srt", "selectedIds": [2, 0, 3, 1]},
                {"type": "mcq", "selectedIndex": 0},
            ]},
            released=True,
        )
        self._add_quiz(
            students["student"],
            ep["第一单元：语法自测"],
            {"questions": [
                {"type": "mcq", "selectedIndex": 0},
                {"type": "mrq", "selectedIds": [0, 1, 4]},
                {"type": "srt", "selectedIds": [0, 3, 1, 2]},
                {"type": "mcq", "selectedIndex": 0},
            ]},
            released=True,
        )
        self._add_quiz(
            students["Frank"],
            ep["第一单元：语法自测"],
            {"questions": [
                {"type": "mcq", "selectedIndex": 0},
                {"type": "mrq", "selectedIds": [0, 1, 4]},
                {"type": "srt", "selectedIds": [2, 0, 3, 1]},
                {"type": "mcq", "selectedIndex": 2},
            ]},
            released=True,
        )
        self._add_quiz(
            students["Ivy"],
            ep["第一单元：语法自测"],
            {"questions": [
                {"type": "mcq", "selectedIndex": 0},
                {"type": "mrq", "selectedIds": [0, 1, 4]},
                {"type": "srt", "selectedIds": [2, 0, 3, 1]},
                {"type": "mcq", "selectedIndex": 0},
            ]},
            released=True,
        )

        # FRQ quiz: awaiting review by default.
        self._add_quiz(
            students["Emma"],
            ep["第二单元：运算测验"],
            {"questions": [
                {"type": "mcq", "selectedIndex": 0},
                {"type": "mcq", "selectedIndex": 0},
                {"type": "frq", "text": "把字符串或数字转换成整数。"},
            ]},
            released=False,
        )
        self._add_quiz(
            students["Frank"],
            ep["第二单元：运算测验"],
            {"questions": [
                {"type": "mcq", "selectedIndex": 1},
                {"type": "mcq", "selectedIndex": 0},
                {"type": "frq", "text": "读取用户输入。"},
            ]},
            released=False,
        )
        self._add_quiz(
            students["Ivy"],
            ep["第二单元：运算测验"],
            {"questions": [
                {"type": "mcq", "selectedIndex": 0},
                {"type": "mcq", "selectedIndex": 0},
                {"type": "frq", "text": "int() 可以把字符串转换为整数，例如 int('5') 得到 5。"},
            ]},
            released=False,
        )
        self._add_quiz(
            students["Kate"],
            ep["第二单元：运算测验"],
            {"questions": [
                {"type": "mcq", "selectedIndex": 0},
                {"type": "mcq", "selectedIndex": 0},
                {"type": "frq", "text": "将字符串或数字转换为整数类型。"},
            ]},
            released=True,
            frq_grades={"2": True},
        )

        self._add_quiz(
            students["Kate"],
            ep["第三单元：综合测验"],
            {"questions": [
                {"type": "mcq", "selectedIndex": 0},
                {"type": "mrq", "selectedIds": [0, 1, 3]},
                {"type": "srt", "selectedIds": [1, 0, 2]},
                {"type": "mcq", "selectedIndex": 0},
            ]},
            released=True,
        )
        self._add_quiz(
            students["Leo"],
            ep["第三单元：综合测验"],
            {"questions": [
                {"type": "mcq", "selectedIndex": 0},
                {"type": "mrq", "selectedIds": [0, 1]},
                {"type": "srt", "selectedIds": [1, 0, 2]},
                {"type": "mcq", "selectedIndex": 0},
            ]},
            released=True,
        )

        code_sum = "a = int(input())\nb = int(input())\nprint(a + b)\n"
        code_sum_tests = [
            {"passed": True, "input": "1\n2", "expected": "3", "actual": "3"},
            {"passed": True, "input": "5\n6", "expected": "11", "actual": "11"},
            {"passed": True, "input": "132\n23", "expected": "155", "actual": "155"},
        ]
        for username in ("student", "Emma", "Frank", "Grace", "Leo"):
            self._add_code(students[username], ep["两数之和"], code_sum, code_sum_tests)

        code_odd = 'n = int(input())\nprint("Even" if n % 2 == 0 else "Odd")\n'
        code_odd_tests = [
            {"passed": True, "input": "4", "expected": "Even", "actual": "Even"},
            {"passed": True, "input": "7", "expected": "Odd", "actual": "Odd"},
            {"passed": True, "input": "0", "expected": "Even", "actual": "Even"},
        ]
        for username in ("Ivy", "Kate", "Leo"):
            self._add_code(students[username], ep["判断奇偶"], code_odd, code_odd_tests)

        # One failing code submission to make review more realistic.
        self._add_code(
            students["Jack"],
            ep["判断奇偶"],
            'n = int(input())\nprint("Odd" if n % 2 == 0 else "Even")\n',
            [
                {"passed": False, "input": "4", "expected": "Even", "actual": "Odd"},
                {"passed": False, "input": "7", "expected": "Odd", "actual": "Even"},
                {"passed": False, "input": "0", "expected": "Even", "actual": "Odd"},
            ],
        )

    def _add_quiz(self, user, episode, payload, released, frq_grades=None):
        QuizSubmission.objects.update_or_create(
            user=user,
            episode=episode,
            defaults={
                "answers": json.dumps(payload, ensure_ascii=False),
                "frq_grades": json.dumps(frq_grades or {}, ensure_ascii=False),
                "released_at": timezone.now() if released else None,
            },
        )
        EpisodeReadStatus.objects.update_or_create(
            user=user,
            episode=episode,
            defaults={"is_read": True},
        )

    def _add_code(self, user, episode, code, test_results):
        CodeSubmission.objects.update_or_create(
            user=user,
            episode=episode,
            defaults={
                "code": code,
                "test_results": json.dumps(test_results, ensure_ascii=False),
                "is_submitted": True,
                "submitted_at": timezone.now(),
            },
        )
        EpisodeReadStatus.objects.update_or_create(
            user=user,
            episode=episode,
            defaults={"is_read": True},
        )
