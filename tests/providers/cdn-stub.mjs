// anthropic.js imports the SDK from jsDelivr, which Node cannot load; this points that URL at a local stub.
// Import this first, then load anything that reaches anthropic.js (index.js does) with a dynamic import():
// static imports are all resolved before this file runs.
import module from "node:module";

const SDK = "https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@";
const STUB = new URL("./anthropic-sdk-stub.mjs", import.meta.url).href;
module.registerHooks({
  resolve: (specifier, context, next) => (specifier.startsWith(SDK) ? { url: STUB, shortCircuit: true } : next(specifier, context)),
});
