---
name: user-driven-debugging
description: Debugging methodology when the user has already found a fix manually — replicate and automate it programmatically
tags: [debugging, methodology, workflow]
---

# User-Driven Debugging: Replicate What Worked

## The Pattern

The user found a fix through trial and error (e.g., refreshing the page, restarting a service, toggling a setting). They tell you what worked. Your job: understand *why* it worked and encode it as an automatic behavior so they never have to do it manually again.

## Workflow

### 1. Characterize the fix
When the user says "refreshing the page fixed it" or "restarting X fixed it", ask:
- What state does the fix reset? (page refresh = full React state + browser APIs; service restart = in-memory state + connections)
- Where in the code lifecycle does that reset need to happen?
- Is there an in-app equivalent that's less disruptive? (e.g., `onRefresh()` instead of full page reload)

### 2. Find the in-app equivalent
| User's manual fix | In-app equivalent to try first |
|---|---|
| Full page refresh | Call the framework's refresh/reset hook on action exit |
| Browser back/forward | Call `onNavigate` or `router.go(-1)` |
| Sign out + back in | Call `Auth.signOut()` + re-authenticate |
| Close + reopen modal | Unmount/remount component (add `key` prop that increments) |
| Restart service | Re-initialize client / reconnect |
| Clear localStorage | `localStorage.removeItem(key)` or `localStorage.clear()` |
| Hard reload (Ctrl+Shift+R) | Clear caches + framework refresh hook |

### 3. Apply least-disruptive equivalent first
Try progressively more aggressive resets:
1. State reset (`setState(initialValue)`)
2. Framework refresh hook (e.g., Amplify's `onRefresh()`)
3. Component remount (`key` increment)
4. Full data refetch
5. Full page reload (`window.location.reload()`) — last resort

### 4. Wire it to the right trigger
The fix must fire automatically at the same point the user's manual action would have. Common trigger points:
- After a custom action exits → call refresh in the `onActionExit` wrapper
- After a modal closes → call reset in `onClose`
- After a form submits → call `invalidate()` / `refetch()`
- After an error state → add a retry that re-initializes

### 5. Verify the fix covers all exit paths
The most common mistake: fixing the "happy path" exit but missing Cancel, Back, error dismissal, and keyboard Escape. Audit every button and key handler that exits the component.

## Example: Amplify Storage Browser Custom Action

**User reported:** "I have to refresh the page to use Rename or Storage Info after the first use."

**Analysis:**
- Page refresh resets Amplify's internal action state machine
- The no-op handler (`Promise.resolve({ status: 'COMPLETE' })`) resolves immediately, possibly leaving the state machine in a terminal state

**In-app equivalent found:** `onRefresh()` from `useView('LocationDetail')` — triggers Amplify's file-list refresh which also resets the action state

**Implementation:**
```typescript
const exit = () => { onRefresh?.(); onActionExit(); };
// Replace all onActionExit calls in the view with exit()
```

**All exit paths covered:** Done button (success), Cancel button (idle), Back button (error/no-selection), Close button — all wired to `exit`.

## Anti-Patterns to Avoid

- **Fixing only the happy-path exit** — user still hits the bug when they Cancel
- **Using `window.location.reload()`** — always try a framework-level reset first; full reload is jarring and loses unsaved state
- **Putting the fix in a useEffect cleanup** — cleanups run on unmount, not on user action; wire to the button handler instead
- **Assuming the root cause** — document it as "unconfirmed" if you can't read the framework source; the fix is what matters
