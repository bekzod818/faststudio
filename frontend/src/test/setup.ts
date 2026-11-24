import "@testing-library/jest-dom/vitest";

// jsdom lacks the Pointer Capture API that Radix primitives call on pointer
// events; provide inert stand-ins so user-event clicks behave as in browsers.
for (const name of ["hasPointerCapture", "setPointerCapture", "releasePointerCapture"] as const) {
  if (!(name in Element.prototype)) {
    Object.defineProperty(Element.prototype, name, {
      configurable: true,
      value: name === "hasPointerCapture" ? () => false : () => undefined,
    });
  }
}
