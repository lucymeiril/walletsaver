const fs = require('fs');
const path = require('path');

const dirs = [
  'E:\\pdf\\capston01\\walletSavior\\.github\\workflows',
  'E:\\pdf\\capston01\\walletSavior\\.github\\ISSUE_TEMPLATE'
];

try {
  dirs.forEach(dir => {
    fs.mkdirSync(dir, { recursive: true });
    console.log(`Created: ${dir}`);
  });
  console.log('\n✓ All directories created successfully!');
} catch (err) {
  console.error('Error:', err.message);
  process.exit(1);
}
