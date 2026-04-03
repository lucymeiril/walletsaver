const fs = require('fs');
const path = require('path');

const adminApiPath = 'E:\\pdf\\capston01\\walletSavior\\admin\\admin-api';
const adminFrontendPath = 'E:\\pdf\\capston01\\walletSavior\\admin\\admin-frontend';

// Create directories recursively
fs.mkdirSync(adminApiPath, { recursive: true });
fs.mkdirSync(adminFrontendPath, { recursive: true });

// Verify they exist
const dir1Exists = fs.existsSync(adminApiPath);
const dir2Exists = fs.existsSync(adminFrontendPath);

console.log('✓ Directories created successfully:');
console.log('  - ' + adminApiPath);
console.log('  - ' + adminFrontendPath);

if (dir1Exists && dir2Exists) {
    console.log('\n✓ Verification passed: Both directories exist');
    
    // List contents of admin folder
    const adminDir = 'E:\\pdf\\capston01\\walletSavior\\admin';
    const contents = fs.readdirSync(adminDir, { withFileTypes: true });
    console.log('\nContents of admin folder:');
    contents.forEach(item => {
        if (item.isDirectory()) {
            console.log('  [DIR] ' + item.name);
        }
    });
} else {
    console.error('Error: One or more directories were not created');
    process.exit(1);
}
