/**
 * 플러그인 시스템 배럴 export
 */

// SDK
export { MessageBridge } from './sdk/MessageBridge.js';
export { PluginAPI } from './sdk/PluginAPI.js';

// Runtime
export { default as PluginSandbox, buildSandboxAttr } from './runtime/PluginSandbox.jsx';
export { default as PluginHost, VALID_SLOTS } from './runtime/PluginHost.jsx';
export { PermissionManager } from './runtime/PermissionManager.js';

// Manager
export { usePluginStore } from './manager/PluginStore.js';
export { PluginInstaller } from './manager/PluginInstaller.js';
export { default as PluginMarketplace } from './manager/PluginMarketplace.jsx';

// Schema
export { validateManifest, VALID_PERMISSIONS, VALID_SLOTS as MANIFEST_SLOTS } from './manifest.schema.js';
