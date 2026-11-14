export function validatePayload() {
  return payloadEntries.length > 0;
}

export function validateTarget(target) {
  return target !== "/";
}
