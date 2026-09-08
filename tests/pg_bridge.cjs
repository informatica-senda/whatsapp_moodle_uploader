const {PGlite} = require(process.argv[2]);
const readline = require('node:readline');
const db = new PGlite();
(async () => {
  await db.waitReady;
  const lines = readline.createInterface({input: process.stdin});
  for await (const line of lines) {
    try {
      const request = JSON.parse(line);
      const result = request.exec ? await db.exec(request.sql) : await db.query(request.sql,request.params || []);
      process.stdout.write(JSON.stringify({result})+'\n');
    } catch (e) {
      process.stdout.write(JSON.stringify({error:e.message})+'\n');
    }
  }
  await db.close();
})();
