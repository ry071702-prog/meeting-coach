import { test } from "node:test";
import assert from "node:assert/strict";
import "./cdn-stub.mjs";

const { keyOwner, pastedKey } = await import("../../web/providers/index.js");

test("keyOwner tells each company's key formats apart", () => {
  for (const [key, owner] of [
    ["sk-ant-api03-abc", "anthropic"],
    ["sk-proj-abc", "openai"],
    ["sk-svcacct-abc", "openai"],
    ["sk-abc123", "openai"],
    ["AIzaSyabc", "gemini"],
  ]) assert.equal(keyOwner(key), owner, key);
});

test("keyOwner knows a key pasted with a variable name, quotes, a Bearer prefix or a zero-width space", () => {
  for (const [key, owner] of [
    ["ANTHROPIC_API_KEY=sk-ant-api03-abc", "anthropic"],
    ['export OPENAI_API_KEY="sk-proj-abc"', "openai"],
    ["'AIzaSyabc'", "gemini"],
    ["Bearer sk-proj-abc", "openai"],
    ["Authorization: Bearer sk-ant-api03-abc", "anthropic"],
    ["\u200Bsk-ant-api03-abc", "anthropic"],
    ["GEMINI_API_KEY: AIzaSyabc", "gemini"],
  ]) assert.equal(keyOwner(key), owner, key);
});

test("keyOwner lets a format it does not know through", () => {
  for (const key of ["", "my-key", "xai-abc", "Bearer"]) assert.equal(keyOwner(key), null, key);
});

test("pastedKey keeps only the key out of a pasted line, and leaves a format it does not know as typed", () => {
  for (const [text, key] of [
    ['export ANTHROPIC_API_KEY="sk-ant-api03-abc"', "sk-ant-api03-abc"],
    ["Bearer sk-proj-abc ", "sk-proj-abc"],
    ["\u200BAIzaSyabc", "AIzaSyabc"],
    ["  sk-ant-api03-abc\n", "sk-ant-api03-abc"],
    ["  my-own key  ", "my-own key"],
  ]) assert.equal(pastedKey(text), key, text);
});
