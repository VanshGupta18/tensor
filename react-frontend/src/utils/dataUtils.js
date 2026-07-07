export const getPathValue = (obj, path) => {
  return path.split('.').reduce((acc, part) => acc && acc[part], obj);
};

export const applyEditsToData = (data, edits) => {
  const newData = JSON.parse(JSON.stringify(data));
  Object.keys(edits).forEach(path => {
    const parts = path.split('.');
    const last = parts.pop();
    let current = newData;
    parts.forEach(part => {
      if (current[part] === undefined) current[part] = {};
      current = current[part];
    });
    let val = edits[path];
    const currentVal = current[last];
    if (currentVal != null && typeof currentVal === 'number' && val !== '' && !isNaN(Number(val))) {
      val = Number(val);
    } else if (currentVal != null && typeof currentVal === 'boolean') {
      val = val === 'true';
    }
    current[last] = val;
  });
  return newData;
};
