import type { ErrorCode, FieldMeta, FieldType, MetaResponse } from "./contract.gen";

// Compile-time guard: adding a FieldType on the backend without handling it
// here fails `tsc` (exhaustive switch over the generated union).
function widgetFor(type: FieldType): string {
  switch (type) {
    case "foreign_key":
      return "combobox";
    case "string":
    case "uuid":
    case "decimal":
      return "input";
    case "text":
    case "json":
      return "textarea";
    case "integer":
    case "float":
      return "number";
    case "boolean":
      return "switch";
    case "date":
      return "date";
    case "datetime":
      return "datetime";
    case "enum":
      return "select";
    case "unsupported":
      return "readonly";
    default: {
      const unhandled: never = type;
      return unhandled;
    }
  }
}

const field: FieldMeta = {
  name: "team_id",
  label: "Team",
  type: "foreign_key",
  nullable: true,
  required: false,
  readonly: false,
  create_only: false,
  primary_key: false,
  default: null,
  has_default: false,
  max_length: null,
  min_value: -2147483648,
  max_value: 2147483647,
  choices: null,
  relation: { target_identity: "teams", target_field: "id", value_type: "integer" },
  timezone: null,
  precision: null,
  scale: null,
  help_text: null,
};

const meta: MetaResponse = {
  schema_version: "1",
  version: "0.1.0",
  title: "FastStudio",
  show_powered_by: true,
  user: { id: "1", username: "admin" },
  models: [
    {
      identity: "users",
      name: "User",
      name_plural: "Users",
      icon: null,
      pk_field: "id",
      list_display: ["id", "team_id"],
      search_fields: [],
      list_filter: [{ field: "is_active", kind: "boolean", choices: [] }],
      ordering: ["-id"],
      sortable_fields: ["id", "team_id"],
      account: null,
      page_size: 25,
      permissions: { create: true, edit: true, delete: false },
      fields: [field],
    },
  ],
};

describe("generated API contract", () => {
  it("covers every field type with a widget", () => {
    expect(widgetFor(field.type)).toBe("combobox");
    expect(widgetFor("unsupported")).toBe("readonly");
  });

  it("types the metadata payload", () => {
    expect(meta.models[0]?.fields[0]?.relation?.target_identity).toBe("teams");
    const code: ErrorCode = "csrf_failed";
    expect(code).toBe("csrf_failed");
  });
});
