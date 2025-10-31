public record CreateDashboardRequest(
    string title,          // obrigatório
    string? table,         // opcional
    string? panelType,     // "table", "timeseries", "barchart", etc.
    string? panelTitle,    // opcional
    string? rawSql,        // opcional; obrigatório se não houver table
    string? datasourceUid  // opcional
);