import { ArrowLeft, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { isForbidden } from "@/api/errors";
import type { LinkCount, ModelMeta } from "@/api/contract.gen";
import {
  useCreateItem,
  useDeleteItem,
  useItem,
  useLinkCounts,
  useMeta,
  useUpdateItem,
} from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { RecordForm } from "@/features/form/RecordForm";
import { isOwnAccount, withProtectedFields } from "@/features/record/account";
import { ModelGate } from "@/features/model/ModelGate";
import { inSentence, routes } from "@/features/model/routes";
import { toast } from "@/lib/toast";
import { SKIP_GUARD } from "@/lib/unsaved";
import { NoAccessPage } from "@/pages/NoAccessPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

function BackToList({ model }: { model: ModelMeta }) {
  return (
    <Link
      to={routes.list(model.identity)}
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft aria-hidden className="size-4" />
      {model.name_plural}
    </Link>
  );
}

function linkText(link: LinkCount, own: string, models: ModelMeta[]): string {
  const count = `${String(link.count)} ${link.count === 1 ? "link" : "links"}`;
  if (link.identity === own) return `${count} in ${link.label}`;
  const owner = models.find((model) => model.identity === link.identity)?.name_plural;
  return `${count} in ${owner ?? link.identity} › ${link.label}`;
}

/** The confirmation text: what else the delete removes, then "cannot be undone". */
function DeleteDescription({
  identity,
  models,
  links,
}: {
  identity: string;
  models: ModelMeta[];
  links: ReturnType<typeof useLinkCounts>;
}) {
  const removed = links.data?.items.filter((link) => link.count > 0) ?? [];
  return (
    <>
      {links.isPending && links.fetchStatus !== "idle" && (
        <p>Counting the links this delete removes…</p>
      )}
      {links.isError && <p>Could not count the links this delete removes.</p>}
      {removed.length > 0 && (
        <>
          <p>This also removes:</p>
          <ul className="my-2 list-disc pl-5">
            {removed.map((link) => (
              <li key={`${link.identity}\u0000${link.field}`}>
                {linkText(link, identity, models)}
              </li>
            ))}
          </ul>
        </>
      )}
      <p>This cannot be undone.</p>
    </>
  );
}

/** Route element for `/models/:identity/new`. */
export function CreateRoute() {
  return <ModelGate>{(model) => <CreatePage key={model.identity} model={model} />}</ModelGate>;
}

function CreatePage({ model }: { model: ModelMeta }) {
  const navigate = useNavigate();
  const create = useCreateItem(model.identity);
  const name = inSentence(model.name);
  return (
    <section className="flex flex-col gap-4">
      <BackToList model={model} />
      <h1 className="text-2xl font-semibold">Add {name}</h1>
      {model.permissions.create ? (
        <RecordForm
          model={model}
          mode="create"
          submitLabel={`Create ${name}`}
          onSubmit={(body) => create.mutateAsync(body)}
          onSaved={(row) => {
            toast.success(`${model.name} created.`);
            void navigate(routes.record(model.identity, row.pk), { replace: true });
          }}
        />
      ) : (
        <p role="alert">Adding {inSentence(model.name_plural)} is disabled.</p>
      )}
    </section>
  );
}

/** Route element for `/models/:identity/items/:pk`. */
export function RecordRoute() {
  const { pk = "" } = useParams();
  return (
    <ModelGate>
      {(model) => <RecordPage key={`${model.identity}\u0000${pk}`} model={model} pk={pk} />}
    </ModelGate>
  );
}

function RecordPage({ model, pk }: { model: ModelMeta; pk: string }) {
  const navigate = useNavigate();
  const item = useItem(model.identity, pk);
  const update = useUpdateItem(model.identity, pk);
  const remove = useDeleteItem(model.identity, pk);
  const meta = useMeta().data;
  const userId = meta?.user.id;
  const models = meta?.models ?? [];
  const [confirming, setConfirming] = useState(false);
  // Always asked: the server knows every field a delete affects (inheritance included).
  const links = useLinkCounts(model.identity, pk, confirming);
  const title = `${model.name} ${pk}`;

  if (item.isPending) return <p role="status">Loading…</p>;
  if (item.isError) {
    if (item.error instanceof ApiError && item.error.code === "not_found") return <NotFoundPage />;
    if (isForbidden(item.error)) return <NoAccessPage />;
    return <p role="alert">Could not load this {inSentence(model.name)}. Try again later.</p>;
  }

  // The server refuses these changes on one's own account (409 self_lockout).
  const own = isOwnAccount(model, item.data, userId);
  const canDelete = model.permissions.delete && !own;
  const lockedFields = model.permissions.edit && (model.account?.protected_fields.length ?? 0) > 0;
  const ownHint = !own
    ? null
    : lockedFields
      ? "This is your account: you cannot change your own sign-in status or delete it here."
      : model.permissions.delete
        ? "This is your account: you cannot delete it here."
        : null;

  const deleteRecord = () => {
    remove.mutate(undefined, {
      onSuccess: () => {
        setConfirming(false);
        toast.success(`${title} deleted.`);
        // The record is gone: unsaved edits to it cannot be kept. Leave its
        // page before dropping it from the cache (a mounted page would refetch).
        void Promise.resolve(
          navigate(routes.list(model.identity), { replace: true, state: SKIP_GUARD }),
        ).then(remove.forget);
      },
      onError: (error) => {
        setConfirming(false);
        toast.error(error instanceof ApiError ? error.message : "Deleting failed. Try again.");
      },
    });
  };

  return (
    <section className="flex flex-col gap-4">
      <BackToList model={model} />
      <h1 className="text-2xl font-semibold">{title}</h1>
      {!model.permissions.edit && (
        <p className="text-sm text-muted-foreground">
          Editing {inSentence(model.name_plural)} is disabled.
        </p>
      )}
      {ownHint !== null && <p className="text-sm text-muted-foreground">{ownHint}</p>}
      <RecordForm
        model={own ? withProtectedFields(model) : model}
        mode="edit"
        row={item.data}
        readOnly={!model.permissions.edit}
        submitLabel="Save changes"
        onSubmit={(body) => update.mutateAsync(body)}
        onSaved={() => {
          toast.success("Changes saved.");
        }}
        actions={
          canDelete ? (
            <Button
              type="button"
              variant="outline"
              className="ml-auto text-destructive"
              onClick={() => {
                setConfirming(true);
              }}
            >
              <Trash2 aria-hidden className="size-4" />
              Delete
            </Button>
          ) : undefined
        }
      />
      <ConfirmDialog
        open={confirming}
        title={`Delete ${title}?`}
        description={<DeleteDescription identity={model.identity} models={models} links={links} />}
        confirmLabel={remove.isPending ? "Deleting…" : "Delete"}
        destructive
        busy={remove.isPending}
        onConfirm={deleteRecord}
        onCancel={() => {
          setConfirming(false);
        }}
      />
    </section>
  );
}
