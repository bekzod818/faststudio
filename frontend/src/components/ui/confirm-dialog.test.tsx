import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ConfirmDialog } from "./confirm-dialog";

function renderDialog(props: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const view = render(
    <ConfirmDialog
      open
      title="Delete thing?"
      description="This cannot be undone."
      confirmLabel="Delete"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...props}
    />,
  );
  return { ...view, onConfirm, onCancel };
}

describe("ConfirmDialog", () => {
  it("is a labelled modal that focuses the safe choice", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog", { name: "Delete thing?" });
    expect(dialog).toHaveAccessibleDescription("This cannot be undone.");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("confirms and cancels", async () => {
    const { onConfirm, onCancel } = renderDialog();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("reports a native close as cancel", () => {
    const { onCancel } = renderDialog();
    screen.getByRole("dialog").dispatchEvent(new Event("close"));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("stays open while busy", () => {
    const { onCancel } = renderDialog({ busy: true });
    const dialog = screen.getByRole<HTMLDialogElement>("dialog");
    dialog.close();
    expect(onCancel).not.toHaveBeenCalled();
    expect(dialog.open).toBe(true);
  });
});
