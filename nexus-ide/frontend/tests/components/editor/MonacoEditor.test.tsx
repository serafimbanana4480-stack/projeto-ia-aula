import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * MonacoEditor.tsx is a 38-line wrapper whose entire job is translating four
 * props into `@monaco-editor/react`'s API. That translation is what this file
 * tests: `path`, `language`, `value`, the VS Code-parity `options` block, and
 * the `next ?? ""` coercion in its onChange handler.
 *
 * WHAT IS AND IS NOT COVERED
 * --------------------------
 * COVERED:   every line of components/editor/MonacoEditor.tsx -- that each prop
 *            is forwarded, that the theme/height/options are what the file
 *            claims, and that a null/undefined editor change is coerced to "".
 * NOT COVERED: Monaco itself. It needs a real browser (workers, canvas,
 *            measured DOM), so it cannot mount in jsdom. The global mock in
 *            tests/setup.ts renders `null` for the same reason. Testing Monaco
 *            is out of scope; testing this wrapper is not, and previously
 *            nothing did -- the file was an `expect(true).toBe(true)` stub that
 *            imported nothing at all.
 *
 * The mock is declared here rather than relying on tests/setup.ts so the props
 * are observable; setup.ts's mock returns null and would assert nothing.
 */

const editorProps = vi.fn();

vi.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: (props: Record<string, unknown>) => {
    editorProps(props);
    return <div data-testid="monaco-stub" />;
  },
}));

import MonacoEditor from "../../../components/editor/MonacoEditor";

function lastProps() {
  const calls = editorProps.mock.calls;
  expect(calls.length).toBeGreaterThan(0);
  return calls[calls.length - 1][0] as Record<string, never>;
}

describe("MonacoEditor", () => {
  beforeEach(() => {
    editorProps.mockClear();
  });

  it("repassa path, language e value ao editor", () => {
    render(
      <MonacoEditor path="src/app.tsx" language="typescript" value="const a = 1;" onChange={() => {}} />,
    );

    const props = lastProps();
    expect(props.path).toBe("src/app.tsx");
    expect(props.language).toBe("typescript");
    expect(props.value).toBe("const a = 1;");
  });

  it("usa o tema vs-dark e altura total, como documentado", () => {
    render(<MonacoEditor path="a.ts" language="ts" value="" onChange={() => {}} />);

    const props = lastProps();
    expect(props.theme).toBe("vs-dark");
    expect(props.height).toBe("100%");
  });

  it("aplica o bloco de opções de paridade com o VS Code", () => {
    render(<MonacoEditor path="a.ts" language="ts" value="" onChange={() => {}} />);

    const options = lastProps().options as Record<string, unknown>;
    expect(options.minimap).toEqual({ enabled: true });
    expect(options.fontSize).toBe(13);
    expect(options.fontFamily).toContain("SF Mono");
    expect(options.smoothScrolling).toBe(true);
    expect(options.cursorSmoothCaretAnimation).toBe("on");
    expect(options.automaticLayout).toBe(true);
  });

  it("propaga o novo valor para onChange", () => {
    const onChange = vi.fn();
    render(<MonacoEditor path="a.ts" language="ts" value="" onChange={onChange} />);

    (lastProps().onChange as (next?: string) => void)("const b = 2;");

    expect(onChange).toHaveBeenCalledWith("const b = 2;");
  });

  it("converte um valor nulo do editor em string vazia", () => {
    // Monaco emits `undefined` when the model is disposed mid-edit. Without the
    // `next ?? ""` coercion that would set component state to undefined, and a
    // controlled editor bound to `value={undefined}` is a controlled/uncontrolled
    // React warning at best.
    const onChange = vi.fn();
    render(<MonacoEditor path="a.ts" language="ts" value="" onChange={onChange} />);

    (lastProps().onChange as (next?: string) => void)(undefined);

    expect(onChange).toHaveBeenCalledWith("");
    expect(onChange.mock.calls[0][0]).not.toBeUndefined();
  });
});
