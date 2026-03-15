const CANONICAL_ENTITY_PREFIXES = [
  "ip:",
  "service_id:",
  "endpoint:",
  "account_h:",
  "phone_h:",
  "person_h:",
  "device_id:",
  "domain:",
  "url:",
  "agent_id:",
  "provider_id:",
];

export function isCanonicalEntityKey(value: string | null | undefined): boolean {
  const trimmed = value?.trim() ?? "";
  return CANONICAL_ENTITY_PREFIXES.some((prefix) => trimmed.startsWith(prefix));
}

export function canonicalServiceKey(serviceId: string): string {
  const trimmed = serviceId.trim();
  return trimmed.startsWith("service_id:") ? trimmed : `service_id:${trimmed}`;
}

export function canonicalEndpointKey(endpoint: string): string {
  const trimmed = endpoint.trim();
  return trimmed.startsWith("endpoint:") ? trimmed : `endpoint:${trimmed}`;
}

export function displayEntityLabel(entityKey: string): string {
  if (!isCanonicalEntityKey(entityKey)) return entityKey;
  const [, ...rest] = entityKey.split(":");
  return rest.join(":") || entityKey;
}

