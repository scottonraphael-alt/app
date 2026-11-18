// JSDOM has no layout observer. Real geometry and tooltip placement are checked in the browser.
if (typeof ResizeObserver === 'undefined') {
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
