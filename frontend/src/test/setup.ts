import "@testing-library/jest-dom/vitest";

// jsdom lacks the Pointer Capture API that Radix primitives call on pointer
// events; provide inert stand-ins so user-event clicks behave as in browsers.
// jsdom has no <dialog> modal support; mimic open/close well enough for tests.
if (typeof HTMLDialogElement !== "undefined" && !("showModal" in HTMLDialogElement.prototype)) {
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: {
      configurable: true,
      value(this: HTMLDialogElement) {
        this.open = true;
      },
    },
    close: {
      configurable: true,
      value(this: HTMLDialogElement) {
        this.open = false;
        this.dispatchEvent(new Event("close"));
      },
    },
  });
}

for (const name of ["hasPointerCapture", "setPointerCapture", "releasePointerCapture"] as const) {
  if (!(name in Element.prototype)) {
    Object.defineProperty(Element.prototype, name, {
      configurable: true,
      value: name === "hasPointerCapture" ? () => false : () => undefined,
    });
  }
}
