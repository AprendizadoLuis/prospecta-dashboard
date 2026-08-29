const fs = require("fs");
const { Client } = require("pg");

function getDatabaseUrl() {
    const envLine = fs
        .readFileSync(".env", "utf8")
        .split(/\r?\n/)
        .find((line) => line.startsWith("AGENDA_DATABASE_URL="));

    if (!envLine) {
        throw new Error("AGENDA_DATABASE_URL não está configurada no arquivo .env.");
    }

    return envLine.slice("AGENDA_DATABASE_URL=".length);
}

async function inspectSchema() {
    const client = new Client({ connectionString: getDatabaseUrl() });

    try {
        await client.connect();
        const result = await client.query(`
            select table_schema, table_name
            from information_schema.tables
            where table_schema not in ('pg_catalog', 'information_schema')
            order by table_schema, table_name
        `);
        console.log(JSON.stringify(result.rows));
    } finally {
        await client.end();
    }
}

inspectSchema().catch((error) => {
    console.error("Falha ao consultar schema:", error.message);
    process.exit(1);
});
