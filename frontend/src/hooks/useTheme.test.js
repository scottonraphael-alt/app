import React, { act } from "react";
import { createRoot } from "react-dom/client";
import useTheme from "./useTheme";

window.IS_REACT_ACT_ENVIRONMENT = true;

test("cycle clair, sombre, système et pose data-theme", () => {
  window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  window.localStorage.setItem("iris.theme", "light");
  let api;
  function Probe() { api = useTheme(); return null; }
  const container = document.createElement("div");
  const root = createRoot(container);
  act(() => root.render(<Probe />));
  expect(api.preference).toBe("light");
  act(() => api.cycleTheme());
  expect(api.preference).toBe("dark");
  expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  expect(window.localStorage.getItem("iris.theme")).toBe("dark");
  act(() => api.cycleTheme());
  expect(api.preference).toBe("system");
  act(() => root.unmount());
});
