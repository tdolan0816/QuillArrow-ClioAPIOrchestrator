# Bulk preview, execute, cancel

Preview is Clio **reads** only. Execute **writes**. Cancel on preview stops the loop. Cancel on execute stops the loop then reverse-PATCHes every successful audit row for that job id.

```mermaid
sequenceDiagram
  participant UI
  participant API
  participant Job as bulk_jobs
  participant Thr as Worker thread
  participant Clio
  participant Aud as audit_log

  UI->>API: POST preview or execute CSV
  API->>Job: create_job running
  API-->>UI: job_id
  API->>Thr: start thread
  loop Poll ~2s
    UI->>API: GET /execute/jobs/id
    API->>Job: read
    API-->>UI: state phase counts
  end
  alt Preview
    Thr->>Clio: GET resolve rows
    Thr->>Job: finish ok results
  else Execute
    Thr->>Clio: GET then PATCH
    Thr->>Aud: before after per row
    Thr->>Job: counters
  end
  opt User clicks Cancel
    UI->>API: POST jobs/id/cancel
    API->>Job: cancel_requested
    Thr->>Thr: checkpoint raises JobCancelled
    opt Execute had audit rows
      Thr->>Clio: reverse PATCH
      Thr->>Aud: revert_* rows
    end
    Thr->>Job: state cancelled
  end
```

Closing the browser is **not** the cancel path. See [[Reliability]].

Related: [[Bulk_Jobs]], [[ADR-004-cooperative-cancel-and-rollback]]
