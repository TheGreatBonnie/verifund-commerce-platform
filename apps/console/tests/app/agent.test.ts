import { describe, expect, it } from "vitest";
import { aguiEndpointUrl } from "@/app/agent";

describe("aguiEndpointUrl", () => {
  it("adds the trailing slash the mounted agent endpoint is served at", () => {
    expect(aguiEndpointUrl("https://gateway.example.com/orchestrator")).toBe(
      "https://gateway.example.com/orchestrator/",
    );
  });

  it("leaves an origin-only URL alone", () => {
    expect(aguiEndpointUrl("http://127.0.0.1:9000")).toBe(
      "http://127.0.0.1:9000/",
    );
  });

  it("keeps a URL that already ends in a slash", () => {
    expect(aguiEndpointUrl("https://gateway.example.com/orchestrator/")).toBe(
      "https://gateway.example.com/orchestrator/",
    );
  });

  it("keeps the query string", () => {
    expect(aguiEndpointUrl("https://gateway.example.com/orchestrator?x=1")).toBe(
      "https://gateway.example.com/orchestrator/?x=1",
    );
  });

  it("returns a value that is not a URL unchanged", () => {
    expect(aguiEndpointUrl("not a url")).toBe("not a url");
  });

  it("returns an empty value unchanged", () => {
    expect(aguiEndpointUrl("")).toBe("");
  });
});
