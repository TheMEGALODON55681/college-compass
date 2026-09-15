"""Generated from the cutoffs table (python -m models.build_round_ratio_table).
Do not hand-edit - rerun the script instead, so this file and the report
below never drift apart.

Fit years: 2016-2022 (2023-2024 carry no round data, docs/KNOWN_ISSUES.md).
100 cells (10 categories x 2 branch families x 5 non-final
round buckets), minimum cell size 55 rows, maximum 8023.

Held-out-year validation (ratio table refit on the other years each time,
never on data that includes the held-out year):
  2021 (6-round season): 37.4% lower MAE overall than the trivial baseline (bucket 1: 49.2%, bucket 2: 33.0%, bucket 3: 31.5%, bucket 4: 29.7%, bucket 5: 27.3%).
  2018 (7-round season): 29.5% lower MAE overall than the trivial baseline (bucket 1: 41.7%, bucket 2: 24.0%, bucket 3: 24.3%, bucket 4: 20.5%, bucket 5: 16.9%).
Both win clearly at every round position. The 7-round year's smaller
margin is expected, not a regression - its keying folds two rounds into
one bucket (docs/BuildLog.md Phase 5 Task 1) - and does not change the
ship decision, since 2021 and 2022 (the two most recent years with round
data) agree on 6 rounds, which is what 2026 is projected to be.

Fit date: 2026-09-14.
"""

RATIO_TABLE = {
    ("EWS", "core", 1): 0.8127, ("EWS", "core", 2): 0.8952, ("EWS", "core", 3): 0.9099, ("EWS", "core", 4): 0.9241, ("EWS", "core", 5): 0.9381,
    ("EWS", "cs_adjacent", 1): 0.8465, ("EWS", "cs_adjacent", 2): 0.9247, ("EWS", "cs_adjacent", 3): 0.9311, ("EWS", "cs_adjacent", 4): 0.9435, ("EWS", "cs_adjacent", 5): 0.9523,
    ("EWS (PwD)", "core", 1): 1.0000, ("EWS (PwD)", "core", 2): 1.0000, ("EWS (PwD)", "core", 3): 1.0000, ("EWS (PwD)", "core", 4): 1.0000, ("EWS (PwD)", "core", 5): 1.0000,
    ("EWS (PwD)", "cs_adjacent", 1): 1.0000, ("EWS (PwD)", "cs_adjacent", 2): 1.0000, ("EWS (PwD)", "cs_adjacent", 3): 1.0000, ("EWS (PwD)", "cs_adjacent", 4): 1.0000, ("EWS (PwD)", "cs_adjacent", 5): 1.0000,
    ("OBC-NCL", "core", 1): 0.8368, ("OBC-NCL", "core", 2): 0.9245, ("OBC-NCL", "core", 3): 0.9398, ("OBC-NCL", "core", 4): 0.9482, ("OBC-NCL", "core", 5): 0.9596,
    ("OBC-NCL", "cs_adjacent", 1): 0.8706, ("OBC-NCL", "cs_adjacent", 2): 0.9532, ("OBC-NCL", "cs_adjacent", 3): 0.9586, ("OBC-NCL", "cs_adjacent", 4): 0.9661, ("OBC-NCL", "cs_adjacent", 5): 0.9759,
    ("OBC-NCL (PwD)", "core", 1): 0.8683, ("OBC-NCL (PwD)", "core", 2): 1.0000, ("OBC-NCL (PwD)", "core", 3): 1.0000, ("OBC-NCL (PwD)", "core", 4): 1.0000, ("OBC-NCL (PwD)", "core", 5): 1.0000,
    ("OBC-NCL (PwD)", "cs_adjacent", 1): 0.9811, ("OBC-NCL (PwD)", "cs_adjacent", 2): 1.0000, ("OBC-NCL (PwD)", "cs_adjacent", 3): 1.0000, ("OBC-NCL (PwD)", "cs_adjacent", 4): 1.0000, ("OBC-NCL (PwD)", "cs_adjacent", 5): 1.0000,
    ("OPEN", "core", 1): 0.8009, ("OPEN", "core", 2): 0.8736, ("OPEN", "core", 3): 0.8862, ("OPEN", "core", 4): 0.9015, ("OPEN", "core", 5): 0.9207,
    ("OPEN", "cs_adjacent", 1): 0.8291, ("OPEN", "cs_adjacent", 2): 0.8989, ("OPEN", "cs_adjacent", 3): 0.9056, ("OPEN", "cs_adjacent", 4): 0.9192, ("OPEN", "cs_adjacent", 5): 0.9337,
    ("OPEN (PwD)", "core", 1): 0.9952, ("OPEN (PwD)", "core", 2): 1.0000, ("OPEN (PwD)", "core", 3): 1.0000, ("OPEN (PwD)", "core", 4): 1.0000, ("OPEN (PwD)", "core", 5): 1.0000,
    ("OPEN (PwD)", "cs_adjacent", 1): 0.9541, ("OPEN (PwD)", "cs_adjacent", 2): 1.0000, ("OPEN (PwD)", "cs_adjacent", 3): 1.0000, ("OPEN (PwD)", "cs_adjacent", 4): 1.0000, ("OPEN (PwD)", "cs_adjacent", 5): 1.0000,
    ("SC", "core", 1): 0.8566, ("SC", "core", 2): 0.9583, ("SC", "core", 3): 0.9747, ("SC", "core", 4): 0.9812, ("SC", "core", 5): 0.9896,
    ("SC", "cs_adjacent", 1): 0.8637, ("SC", "cs_adjacent", 2): 0.9739, ("SC", "cs_adjacent", 3): 0.9859, ("SC", "cs_adjacent", 4): 0.9921, ("SC", "cs_adjacent", 5): 0.9994,
    ("SC (PwD)", "core", 1): 1.0000, ("SC (PwD)", "core", 2): 1.0000, ("SC (PwD)", "core", 3): 1.0000, ("SC (PwD)", "core", 4): 1.0000, ("SC (PwD)", "core", 5): 1.0000,
    ("SC (PwD)", "cs_adjacent", 1): 1.0000, ("SC (PwD)", "cs_adjacent", 2): 1.0000, ("SC (PwD)", "cs_adjacent", 3): 1.0000, ("SC (PwD)", "cs_adjacent", 4): 1.0000, ("SC (PwD)", "cs_adjacent", 5): 1.0000,
    ("ST", "core", 1): 0.8776, ("ST", "core", 2): 1.0000, ("ST", "core", 3): 1.0000, ("ST", "core", 4): 1.0000, ("ST", "core", 5): 1.0000,
    ("ST", "cs_adjacent", 1): 0.8916, ("ST", "cs_adjacent", 2): 1.0000, ("ST", "cs_adjacent", 3): 1.0000, ("ST", "cs_adjacent", 4): 1.0000, ("ST", "cs_adjacent", 5): 1.0000,
    ("ST (PwD)", "core", 1): 1.0000, ("ST (PwD)", "core", 2): 1.0000, ("ST (PwD)", "core", 3): 1.0000, ("ST (PwD)", "core", 4): 1.0000, ("ST (PwD)", "core", 5): 1.0000,
    ("ST (PwD)", "cs_adjacent", 1): 1.0000, ("ST (PwD)", "cs_adjacent", 2): 1.0000, ("ST (PwD)", "cs_adjacent", 3): 1.0000, ("ST (PwD)", "cs_adjacent", 4): 1.0000, ("ST (PwD)", "cs_adjacent", 5): 1.0000,
}
