//go:build windows

package secret

// permissionsNotEnforced reports whether Unix mode bits are meaningless here.
// On Windows, file ACLs are the access control; document that for operators.
func permissionsNotEnforced() bool { return true }
