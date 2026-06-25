const axios = require('axios');
const fs = require('fs');
const FormData = require('form-data');
const contentBuffer = fs.readFileSync('/Users/vanshgupta/Downloads/tensor/FILE_CE-SPD_ ADB_ 2026-27_ T-13_version_2_1779174523191.pdf');
const form = new FormData();
form.append('invoice', contentBuffer, { filename: 'test.pdf', contentType: 'application/pdf' });
axios.post('http://localhost:8000/process_file', form, {
    headers: form.getHeaders(),
    timeout: 600_000
}).then(res => console.log('Success:', res.data)).catch(err => {
    console.error('Error:', err.message);
    if(err.response) console.error('Response body:', err.response.data);
});
