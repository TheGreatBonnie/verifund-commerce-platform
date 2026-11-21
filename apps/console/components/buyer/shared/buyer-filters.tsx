export type BuyerFilterField = {
  key: string;
  label: string;
  options: Array<{ value: string; label: string }>;
};

export function BuyerFilters({
  fields,
  values,
  onChange,
}: {
  fields: BuyerFilterField[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <div className="mm-buyer-filters" role="group" aria-label="Filters">
      {fields.map((field) => (
        <label className="mm-buyer-filter" key={field.key}>
          <span className="mm-buyer-filter-label">{field.label}</span>
          <select
            aria-label={`Filter by ${field.label.toLowerCase()}`}
            value={values[field.key] ?? ""}
            onChange={(event) => onChange(field.key, event.target.value)}
          >
            <option value="">Any</option>
            {field.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      ))}
    </div>
  );
}
