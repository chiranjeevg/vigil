import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { NewProjectLink } from "./NewProjectLink";

describe("NewProjectLink", () => {
  it("links to the setup wizard", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <NewProjectLink />
      </MemoryRouter>,
    );
    expect(html).toContain('href="/setup"');
    expect(html).toMatch(/New project/);
  });
});
