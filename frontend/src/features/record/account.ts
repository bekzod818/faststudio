import type { ModelMeta, Row } from "@/api/contract.gen";

/** True on the signed-in admin's own record of the model that holds accounts (ADR-0009). */
export function isOwnAccount(model: ModelMeta, row: Row, userId: string | undefined): boolean {
  return model.account !== null && userId !== undefined && row.pk === userId;
}

/** The model with its protected account fields shown read-only (the server refuses them). */
export function withProtectedFields(model: ModelMeta): ModelMeta {
  const protectedFields = new Set(model.account?.protected_fields ?? []);
  return {
    ...model,
    fields: model.fields.map((field) =>
      protectedFields.has(field.name) ? { ...field, readonly: true } : field,
    ),
  };
}
