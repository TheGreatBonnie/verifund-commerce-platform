import Link from "next/link";
import { type ReactNode } from "react";

import { Status } from "@/components/ui/status";
import { cn } from "@/lib/cn";
import { formatDate, formatMoney, labelize } from "@/components/buyer/shared/format";

const MONEY_KEY = /(cents|amount|total|price|fee|balance|funds)/i;
const DATE_KEY = /(at|date|time|deadline|created|updated)$/i;
const STATUS_KEY = /(status|state|decision|outcome|result|recommendation)$/i;
const ID_KEY = /(^id$|_id$|^id_)/i;

function statusTone(value: string) {
  if (/fail|error|disput|open|refund|revers|cancel|overdue/i.test(value)) return "error" as const;
  if (/pending|review|await|hold|verif|process|inspect/i.test(value)) return "amber" as const;
  if (/paid|captur|fund|complete|release|resolv|approv/i.test(value)) return "signal" as const;
  return "neutral" as const;
}

export function AdminValue({
  value,
  field,
  currency = "USD",
  depth = 0,
}: {
  value: unknown;
  field?: string;
  currency?: string;
  depth?: number;
}) {
  if (value === null || value === undefined || value === "") {
    return <span className="mm-admin-empty-value">—</span>;
  }
  if (typeof value === "boolean") {
    return <span>{value ? "Yes" : "No"}</span>;
  }
  if (typeof value === "number") {
    if (field && MONEY_KEY.test(field)) return <span>{formatMoney(value, currency)}</span>;
    return <span>{value.toLocaleString("en-US")}</span>;
  }
  if (typeof value === "string") {
    if (field && DATE_KEY.test(field) && !Number.isNaN(new Date(value).getTime())) {
      return <span>{formatDate(value)}</span>;
    }
    if (field && STATUS_KEY.test(field)) {
      return <Status tone={statusTone(value)}>{labelize(value)}</Status>;
    }
    if (field && ID_KEY.test(field)) {
      return <span className="mm-admin-id">{value}</span>;
    }
    return <span>{value}</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="mm-admin-empty-value">None</span>;
    return (
      <ul className="mm-admin-chips">
        {value.map((entry, index) => (
          <li key={`${String(entry)}-${index}`}>
            {typeof entry === "object" ? labelize(String(entry?.type ?? "entry")) : String(entry).replaceAll("_", " ")}
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object") {
    if (depth > 0) {
      return (
        <span className="mm-admin-nested">
          {Object.keys(value as Record<string, unknown>).length} nested fields
        </span>
      );
    }
    return (
      <AdminFields
        data={value as Record<string, unknown>}
        currency={currency}
        compact
        depth={depth + 1}
        testId="admin-nested-fields"
      />
    );
  }
  return <span>{String(value)}</span>;
}

export function AdminFields({
  data,
  columns,
  exclude = [],
  compact = false,
  depth = 0,
  currency = "USD",
  testId = "admin-fields",
}: {
  data?: Record<string, any> | null;
  columns?: string[];
  exclude?: string[];
  compact?: boolean;
  depth?: number;
  currency?: string;
  testId?: string;
}) {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return <p className="mm-admin-empty">No fields available.</p>;
  }
  const preferred = columns ?? [];
  const keys = [
    ...preferred.filter((key) => key in data),
    ...Object.keys(data).filter((key) => !preferred.includes(key)),
  ].filter((key) => !exclude.includes(key));
  if (keys.length === 0) {
    return <p className="mm-admin-empty">No fields available.</p>;
  }
  return (
    <dl className={cn("mm-admin-fields", compact && "is-compact")} data-testid={testId}>
      {keys.map((key) => (
        <div className="mm-admin-field" key={key}>
          <dt>{labelize(key)}</dt>
          <dd>
            <AdminValue value={data[key]} field={key} currency={currency} depth={depth} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

export type AdminColumn = {
  key: string;
  label?: string;
  render?: (value: unknown, row: Record<string, any>) => ReactNode;
};

export function AdminTable({
  title,
  rows,
  columns,
  detailHref,
  emptyLabel,
  currency = "USD",
  testId,
}: {
  title: string;
  rows?: Array<Record<string, any>> | null;
  columns?: AdminColumn[];
  detailHref?: (row: Record<string, any>) => string | null | undefined;
  emptyLabel?: string;
  currency?: string;
  testId?: string;
}) {
  if (!rows || rows.length === 0) {
    return (
      <p className="mm-admin-empty" data-testid={testId}>
        {emptyLabel ?? `No ${title.toLowerCase()} to display.`}
      </p>
    );
  }
  const resolvedColumns: AdminColumn[] =
    columns ??
    Object.keys(rows[0])
      .filter((key) => {
        const value = rows[0][key];
        return value === null || typeof value !== "object";
      })
      .slice(0, 8)
      .map((key) => ({ key }));
  return (
    <div className="mm-admin-table-wrap">
      <table className="mm-admin-table" data-testid={testId}>
        <caption>{title}</caption>
        <thead>
          <tr>
            {resolvedColumns.map((column) => (
              <th scope="col" key={column.key}>
                {column.label ?? labelize(column.key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={String(row.id ?? row.transaction_id ?? rowIndex)}>
              {resolvedColumns.map((column, columnIndex) => {
                const value = row[column.key];
                const href = columnIndex === 0 ? detailHref?.(row) : null;
                const content = column.render ? (
                  column.render(value, row)
                ) : (
                  <AdminValue value={value} field={column.key} currency={currency} />
                );
                return (
                  <td key={column.key}>
                    {href ? <Link href={href}>{content}</Link> : content}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AdminKpis({
  items,
  testId,
}: {
  items: Array<{ label: string; value: ReactNode; hint?: string }>;
  testId?: string;
}) {
  return (
    <div className="mm-admin-kpis" data-testid={testId}>
      {items.map((item) => (
        <div className="mm-admin-kpi" key={item.label}>
          <p className="mm-kicker">{item.label}</p>
          <strong>{item.value}</strong>
          {item.hint ? <small>{item.hint}</small> : null}
        </div>
      ))}
    </div>
  );
}

export function AdminRawDisclosure({
  value,
  label = "View raw response",
}: {
  value: unknown;
  label?: string;
}) {
  return (
    <details className="mm-buyer-raw mm-admin-raw">
      <summary>{label}</summary>
      <pre tabIndex={0}>{JSON.stringify(value ?? {}, null, 2)}</pre>
    </details>
  );
}
