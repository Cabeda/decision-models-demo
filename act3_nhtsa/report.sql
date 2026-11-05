-- Act 3, step 3: measure the labels against ground truth, in plain DuckDB SQL.
--
-- report.py loads the committed sample as `complaints` and data/labels.duckdb
-- as `labels`, then creates one joined view `scored` per model that every
-- query below reads from. Ground truth comes straight from the NHTSA fields:
--   * component    -> the simplified group mapping of COMPDESC (groups.py)
--   * safety flag  -> CRASH='Y' OR FIRE='Y' OR INJURED>0  (a real incident)
--   * severity     -> derived from the same flags
--
-- The view `scored` is created in report.py (it needs the Python group mapping),
-- so these queries assume it exists with columns:
--   model, cmplid, truth_group, pred_group, comp_conf,
--   safety_critical, truth_safety, severity, sev_conf, min_conf, latency_ms


-- 1. Headline: component-group agreement, safety-flag accuracy, mean latency.
--    How often does the model's Choice match the COMPDESC bucket, and how often
--    does its safety Noul (gated at 0.5) match a real crash/fire/injury?
CREATE OR REPLACE TEMP MACRO q_headline() AS TABLE
SELECT
    model,
    count(*)                                               AS rows,
    round(avg((pred_group = truth_group)::INT) * 100, 1)          AS component_agree_pct,
    round(avg(((safety_critical > 0.5) = truth_safety)::INT) * 100, 1) AS safety_acc_pct,
    round(avg((severity >= 2)::INT) FILTER (truth_safety) * 100, 1)    AS sev_hi_on_true_pct,
    round(avg(latency_ms), 0)                              AS mean_latency_ms
FROM scored
GROUP BY model
ORDER BY component_agree_pct DESC;


-- 2. Agreement by confidence band. The promise of a decision model is that it
--    knows when it is unsure: agreement should climb with confidence. The
--    `min_conf` here is the weakest of the three answers on that row (a row is
--    only as trustworthy as its least certain question).
CREATE OR REPLACE TEMP MACRO q_by_confidence() AS TABLE
SELECT
    model,
    CASE
        WHEN comp_conf < 0.25 THEN '1 very low (<.25)'
        WHEN comp_conf < 0.40 THEN '2 low (.25-.40)'
        WHEN comp_conf < 0.60 THEN '3 mid (.40-.60)'
        ELSE                        '4 high (>=.60)'
    END                                           AS confidence_band,
    count(*)                                      AS rows,
    round(avg((pred_group = truth_group)::INT) * 100, 1) AS component_agree_pct
FROM scored
GROUP BY model, confidence_band
ORDER BY model, confidence_band;


-- 3. The "needs human review" bucket. Rows under a confidence Gate are the ones
--    a pipeline would hand to a person; the rest auto-accept. We want the
--    auto-accepted slice to be both LARGE (less human work) and ACCURATE.
CREATE OR REPLACE TEMP MACRO q_review_bucket(gate) AS TABLE
SELECT
    model,
    count(*) FILTER (min_conf <  gate)                         AS to_human,
    count(*) FILTER (min_conf >= gate)                         AS auto_accepted,
    round(100.0 * count(*) FILTER (min_conf >= gate) / count(*), 1) AS auto_pct
FROM scored
GROUP BY model ORDER BY model;


-- 4. THE KEY INSIGHT. Sweep the Gate and show, per model, the trade between how
--    many rows auto-accept and how accurate those auto-accepted rows are. A good
--    decision model buys you a high auto-accept share at high accuracy; a weak
--    one makes you choose between coverage and correctness.
CREATE OR REPLACE TEMP MACRO q_gate_sweep() AS TABLE
WITH gates(g) AS (VALUES (0.0), (0.25), (0.35), (0.50), (0.65), (0.80))
SELECT
    s.model,
    gates.g                                                        AS gate,
    round(100.0 * count(*) FILTER (s.min_conf >= gates.g) / count(*), 1) AS auto_accept_pct,
    round(100.0 * avg((s.pred_group = s.truth_group)::INT)
                  FILTER (s.min_conf >= gates.g), 1)               AS auto_accepted_agree_pct
FROM scored s, gates
GROUP BY s.model, gates.g
ORDER BY s.model, gates.g;
