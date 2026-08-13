---
name: launchdarkly-react-integration
description: "Wire LaunchDarkly into a React and Okta app where user group or role drives flag targeting, including the common failure modes around auth timing."
tags: [launchdarkly, react, okta, feature-flags]
---

# LaunchDarkly React Integration (with Okta auth)

Pattern for wiring LaunchDarkly into a React + Okta app where user group/role determines feature flag targeting.

## Common failure modes (all hit in practice)

### 1. `useEffect` fires before Okta completes
**Symptom:** `/user/profile` call never appears in the network tab even though LD initializes.  
**Cause:** `LDWrapper` mounts before the user authenticates. `useEffect([])` fires once, finds no token in localStorage, returns early, never re-runs.  
**Fix:** Depend on `authState.isAuthenticated` from `useOktaAuth()` so the effect re-runs after login.

```js
const { authState } = useOktaAuth();
const isAuthenticated = authState && authState.isAuthenticated;
React.useEffect(() => {
  if (!isAuthenticated) return;
  // fetch /user/profile and call ldClient.identify()
}, [isAuthenticated]);
```

### 2. `LDProvider` context prop change doesn't re-render consumers
**Symptom:** `/user/profile` returns the right group, `setLdContext` is called, but nav items never appear.  
**Cause:** `LDProvider` v3 doesn't reliably call `identify()` + trigger re-renders when the `context` prop changes from a parent component's `setState`.  
**Fix:** Use `useLDClient()` inside a child component of `LDProvider` and call `ldClient.identify()` directly.

```jsx
function LDIdentifier() {
  const ldClient = useLDClient(); // must be inside LDProvider
  const { authState } = useOktaAuth();
  const isAuthenticated = authState && authState.isAuthenticated;

  React.useEffect(() => {
    if (!isAuthenticated || !ldClient) return;
    // fetch /user/profile, then:
    ldClient.identify({ kind: "user", key: sub, email, group });
  }, [isAuthenticated, ldClient]);

  return null;
}

function LDWrapper({ children }) {
  return (
    <LDProvider clientSideID={clientSideId} context={anonContext}>
      <LDIdentifier />
      {children}
    </LDProvider>
  );
}
```

### 3. `useFlags()` vs `useLDClient().variation()`
**Symptom:** Flag returns `false` even after `identify()` completes.  
**Cause:** `useLDClient().variation()` is a one-shot synchronous read — it doesn't subscribe to flag changes, so components don't re-render when `identify()` completes.  
**Fix:** Use `useFlags()` — it subscribes to flag changes and triggers re-renders automatically. But the React SDK auto-converts kebab-case flag keys to camelCase, so `flags["mfg-qc-access"]` is `undefined`.

```js
import { useFlags } from "launchdarkly-react-client-sdk";

function toCamelCase(key) {
  return key.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

export function useFeatureFlag(flagKey, defaultValue = false) {
  const flags = useFlags();
  return flags[toCamelCase(flagKey)] ?? defaultValue;
}
```

### 4. `clientSideID` resolves to null locally
**Symptom:** No network calls to `app.launchdarkly.com`.  
**Cause:** `app.config.js` switch statement sets the ID from `window.location.hostname`, but something in the resolution returns null instead of `""`.  
**Fix:** Add a fallback in `LDProvider`:
```jsx
<LDProvider clientSideID={config.ldClientSideId || "6a209f98d1b0830a9d7358d4"} ...>
```

### 5. Flag targeting rules vs DB case
**Symptom:** User has `group: "QC"` in context but flag returns false.  
**Cause:** Registration form stores groups lowercase (`toLowerCase()` in the mutation hook). LD targeting rules were set up against lowercase `"qc"`. DB now has uppercase `"QC"` (or vice versa).  
**Fix:** Normalize group to uppercase at the API layer on read, so LD always gets uppercase regardless of what's in the DB. Set LD targeting rules to uppercase.

```python
# Flask /user/profile
group = (authentication.getUserGroup(email) or DEFAULT_GROUP).upper()
```

### 6. LD SDK key in wrong AWS account
**Symptom:** Lambda crashes on startup with `ResourceNotFoundException` from Secrets Manager.  
**Cause:** Lambda is in account A, secret is in account B.  
**Recommended fix:** Pull the secret in CI (CircleCI `build_constants.sh`) and inject as a Lambda env var — same pattern as MySQL/Okta creds. No runtime Secrets Manager call needed.

```bash
# build_constants.sh
LAUNCHDARKLY_SDK_KEY_VAL=$(aws secretsmanager get-secret-value \
  --secret-id launchdarkly_sdk_key | jq -r '.SecretString | fromjson | .key')
echo "LAUNCHDARKLY_SDK_KEY=${LAUNCHDARKLY_SDK_KEY_VAL}" >> ~/myConstants.sh
```

```json
// zappa_settings.json / CircleCI inline
"LAUNCHDARKLY_SDK_KEY": "${LAUNCHDARKLY_SDK_KEY}"
```

```python
# app.py — just read env var, no Secrets Manager call
def _get_ld_sdk_key():
    return os.environ["LAUNCHDARKLY_SDK_KEY"]
```

## Flag setup in LD dashboard
- Flag must have **"Available on client-side SDK"** enabled (Variations tab, not a gear icon in newer UI)
- Targeting rule: `group` attribute `is one of` `["MFG", "QC"]` → serve `true` (variation 0)
- Fallthrough: `false` (variation 1)
- Flag must be **On**

## Debugging checklist
1. Network tab → is there a request to `app.launchdarkly.com`? No = `clientSideID` is null or LDProvider not rendering
2. Console `useFlags()` → is the flag key in `allFlags`? No = "Available on client-side SDK" not enabled
3. Flag value = false for correct group → check case mismatch between DB group and LD targeting rule
4. `/user/profile` not in network tab → `useEffect` bailing early (auth timing issue)
5. `/user/profile` returns correct group but UI doesn't update → `LDProvider` context prop not triggering re-render (use `LDIdentifier` pattern above)
