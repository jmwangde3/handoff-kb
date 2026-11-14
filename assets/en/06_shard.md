# 06 · Log Shard — {{LINE_NAME}}

> Append-only: write records for this line ({{LINE_NAME}}) only, **never edit another session's lines**.
> Each entry is 1–3 lines: `[YYYY-MM-DD HH:MM] {{LINE_NAME}} <what was done → next step>`; anything longer goes here in full, with a summary plus pointer in `05`.
> A **single shard** beyond 200 lines / 60 KB → fold into `90` by topic and leave a heading plus pointer here (act only when crossed).
> Write through `kb-write.py apply` (`operation: append`); never overwrite the whole file.

<!-- kb:id: shard.log -->
## Log

(No entries yet.)
