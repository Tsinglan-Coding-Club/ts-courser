# Submission history, quiz feedback, and course collaboration

## Code submission versions

Each successful **Submit** stores a complete code snapshot, test results, student, episode, and submission time. Identical repeated submissions are still distinct attempts. **Upload**, browser autosave, running tests, and loading an old version do not create attempts. The current uploaded code remains a separate mutable working record; later uploads cannot overwrite submitted history.

Students select an earlier submitted version and load its code into their editor. They can edit or run it before submitting again. Teachers can select historical attempts, including when the student has uploaded a newer unsubmitted draft. Access is limited to the student’s own history or teachers with access to that course.

The migration preserves currently formal-submitted records as initial history entries. Previously overwritten submissions cannot be recovered.

### Why full snapshots

Use full snapshots rather than Git-style deltas for this workload. Small school exercises are generally small text files, and snapshots give constant-complexity retrieval, independent versions, and straightforward backups. Deltas require a reconstruction chain and handling of chain corruption, checkpointing, and diff algorithms without changing the student experience.

Storage scales approximately with `students × code episodes × submissions × (code bytes + result bytes)`. For example, 100 students × 30 episodes × 20 submissions × 10 KB is roughly 600 MB of payload before database overhead. This is an illustrative capacity estimate, not a measured repository workload. Test output can dominate code size; monitor actual database growth before introducing compression, retention rules, or delta storage. There is no automatic history pruning.

Test results are browser-reported; preserving them does not make them independently server-verified grades.

## Per-question quiz feedback

Teachers with edit or manage access can save, revise, or clear plain-text feedback for MCQ, MRQ, SRT, CBA, and FRQ questions. Feedback appears beneath the corresponding question on the student's released results. Unreleased feedback is not included in the student question payload. For quizzes that release immediately, saved feedback appears on the next page load.

Feedback shares the existing submission timestamp check: an outdated review page cannot attach comments to newly submitted answers. Replacing answers clears previous feedback and FRQ grades; resubmitting identical answers preserves them. An empty comment clears that question's feedback. Each comment is limited to 10,000 characters and displayed as escaped text.

Quiz answers and comments still refer to the live quiz's question indexes; this feature does not add quiz question snapshots. Reordering or replacing questions after students submit can affect interpretation of both answers and feedback.

## Course permissions

| Permission | View course and student work | Edit content, grade and comment | Manage teacher access |
| --- | --- | --- | --- |
| View | Yes | No | No |
| Edit | Yes | Yes | No |
| Manage | Yes | Yes | Yes |

The creator receives an ordinary manage membership when the course is created. The creator and later managers have exactly the same authority; either can be demoted or removed by a manager. At least one manager must remain. The creator field records provenance only. Existing courses gain a manager membership for their creator during migration. Platform administrators have full access.

Teacher access is scoped to each course. Assignment of permissions requires a verified teacher account. A teacher with no membership cannot access that course's private student work. Management controls and server endpoints enforce the same permission levels.

## Deployment

Run `uv run python manage.py migrate` before starting the updated application. Back up the database before deployment as usual. The migrations add code history, quiz comments, and course teacher memberships and backfill currently submitted code and existing course creators.
