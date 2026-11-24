import type { FieldMeta, ModelMeta } from "@/api/contract.gen";

export function testField(overrides: Partial<FieldMeta> & Pick<FieldMeta, "name">): FieldMeta {
  return {
    label: overrides.name,
    type: "string",
    nullable: false,
    required: false,
    readonly: false,
    create_only: false,
    primary_key: false,
    default: null,
    has_default: false,
    max_length: null,
    min_value: null,
    max_value: null,
    choices: null,
    relation: null,
    timezone: null,
    precision: null,
    scale: null,
    help_text: null,
    ...overrides,
  };
}

/** A "users" model with one field of each kind the list view cares about. */
export function testModel(overrides: Partial<ModelMeta> = {}): ModelMeta {
  return {
    identity: "users",
    name: "User",
    name_plural: "Users",
    icon: "users",
    pk_field: "id",
    list_display: ["id", "email", "is_active", "status", "team_id"],
    search_fields: ["email"],
    list_filter: [
      { field: "is_active", kind: "boolean", choices: [] },
      {
        field: "status",
        kind: "choice",
        choices: [
          { value: "TODO", label: "Todo" },
          { value: "DONE", label: "Done" },
        ],
      },
    ],
    ordering: ["-id"],
    sortable_fields: ["id", "email"],
    page_size: 2,
    permissions: { create: true, edit: true, delete: true },
    fields: [
      testField({ name: "id", label: "ID", type: "integer", primary_key: true, readonly: true }),
      testField({ name: "email", label: "Email" }),
      testField({ name: "is_active", label: "Is active", type: "boolean" }),
      testField({
        name: "status",
        label: "Status",
        type: "enum",
        nullable: true,
        choices: [
          { value: "TODO", label: "Todo" },
          { value: "DONE", label: "Done" },
        ],
      }),
      testField({
        name: "team_id",
        label: "Team",
        type: "foreign_key",
        nullable: true,
        relation: { target_identity: "teams", target_field: "id", value_type: "integer" },
      }),
    ],
    ...overrides,
  };
}
