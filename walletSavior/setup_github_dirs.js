const fs = require('fs');
const path = require('path');

const basePath = 'E:\\pdf\\capston01\\walletSavior\\.github';
const dir1 = path.join(basePath, 'workflows');
const dir2 = path.join(basePath, 'ISSUE_TEMPLATE');

console.log('Creating directories...\n');

// Create directories
fs.mkdirSync(dir1, { recursive: true });
console.log(`✓ Created: ${dir1}`);

fs.mkdirSync(dir2, { recursive: true });
console.log(`✓ Created: ${dir2}`);

console.log('\n' + '='.repeat(60));
console.log('VERIFICATION - Directory Contents');
console.log('='.repeat(60));

// Verify .github directory
console.log('\n=== .github directory contents ===');
try {
  const items = fs.readdirSync(basePath).sort();
  items.forEach(item => {
    const fullPath = path.join(basePath, item);
    const isDir = fs.statSync(fullPath).isDirectory();
    console.log(`  ${isDir ? '[DIR] ' : '[FILE]'} ${item}`);
  });
} catch (e) {
  console.log(`  Error: ${e.message}`);
}

// Verify workflows directory
console.log('\n=== workflows directory contents ===');
try {
  const items = fs.readdirSync(dir1);
  if (items.length > 0) {
    items.sort().forEach(item => {
      console.log(`  [FILE] ${item}`);
    });
  } else {
    console.log('  (empty directory)');
  }
} catch (e) {
  console.log(`  Error: ${e.message}`);
}

// Verify ISSUE_TEMPLATE directory
console.log('\n=== ISSUE_TEMPLATE directory contents ===');
try {
  const items = fs.readdirSync(dir2);
  if (items.length > 0) {
    items.sort().forEach(item => {
      console.log(`  [FILE] ${item}`);
    });
  } else {
    console.log('  (empty directory)');
  }
} catch (e) {
  console.log(`  Error: ${e.message}`);
}

console.log('\n' + '='.repeat(60));
console.log('✓ All directories created and verified successfully!');
console.log('='.repeat(60));
