//go:build !windows

package secret

// permissionsNotEnforced reports whether Unix mode bits are meaningless here.
func permissionsNotEnforced() bool { return false }
