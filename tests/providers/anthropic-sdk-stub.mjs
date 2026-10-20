// Stands in for the Anthropic SDK that anthropic.js imports from the CDN, so the provider tests run offline.
// The tests hand ask() a fake client directly; this class only records what makeClient passed.
export default class Anthropic {
  constructor(opts) {
    this.opts = opts;
  }
}
