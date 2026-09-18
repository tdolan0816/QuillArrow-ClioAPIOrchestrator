# Custom field bulk update

Each CSV row is one matter + one field. Blank `value` means **CLEAR** (`_destroy` on the existing custom field value instance), not “skip as invalid.” Already-empty + blank value is `NO CHANGE` (no PATCH).

```mermaid
flowchart TD
  csv[CSV row]
  csv --> id[Resolve matter_id or display_number]
  id --> def[Resolve field name to custom field definition]
  def --> read[Read matter custom_field_values]
  read --> pick{Picklist and value set?}
  pick -->|yes| opts[Picklist options once per field per batch]
  pick -->|no| body
  opts --> body[Build PATCH or None]
  body --> preview[Preview shows CREATE UPDATE CLEAR NO CHANGE]
  preview --> exec[Execute PATCH unless patch_body is null]
  exec --> audit[audit_log bulk_update_custom_field]
```

Preview caching: picklist options memoized; matter resolve + CFVs combined when Clio returns them. Still one Clio hit per distinct matter.

Related: [[ADR-005-blank-custom-field-clears]], [[Bulk_Jobs]]
