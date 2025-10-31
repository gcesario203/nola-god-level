using System.Data;
using Microsoft.OpenApi.Models;
using Npgsql;

var builder = WebApplication.CreateBuilder(args);

// Swagger
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo { Title = "Reports API", Version = "v1" });
});

var connString = builder.Configuration.GetConnectionString("Default")
    ?? Environment.GetEnvironmentVariable("ConnectionStrings__Default");

// CORS (libera para dev)
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
        policy.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod());
});

var app = builder.Build();

app.UseCors();

app.UseSwagger();
app.UseSwaggerUI();

// health
app.MapGet("/health", () => Results.Ok(new { status = "ok" }));

app.MapPost("/reports/dashboard", async (CreateDashboardRequest req) =>
{
    // Validação flexível:
    var hasTable = !string.IsNullOrWhiteSpace(req.table);
    var hasRawSql = !string.IsNullOrWhiteSpace(req.rawSql);

    if (string.IsNullOrWhiteSpace(req.title))
        return Results.BadRequest(new { error = "title is required" });

    if (!hasTable && !hasRawSql)
        return Results.BadRequest(new { error = "Provide either table or rawSql" });

    // Config do Grafana via env
    var grafanaUrl = Environment.GetEnvironmentVariable("GRAFANA_URL") ?? "http://grafana:3000";
    var grafanaApiKey = Environment.GetEnvironmentVariable("GRAFANA_API_KEY");
    if (string.IsNullOrWhiteSpace(grafanaApiKey))
        return Results.BadRequest(new { error = "GRAFANA_API_KEY not configured" });

    var panelType = string.IsNullOrWhiteSpace(req.panelType) ? "table" : req.panelType;

    // Se table vier e rawSql não vier, usa um SELECT default; se rawSql vier, usa ele diretamente
    var finalSql = hasRawSql
        ? req.rawSql!.Trim()
        : $"SELECT * FROM {req.table} LIMIT 100";

    // Monta o payload do dashboard Grafana
    var dashboardPayload = new
    {
        dashboard = new
        {
            title = req.title,
            timezone = "browser",
            schemaVersion = 38,
            version = 1,
            refresh = "10s",
            panels = new object[]
            {
                new {
                    id = 1,
                    type = panelType,
                    title = req.panelTitle ?? "Report Panel",
                    gridPos = new { x = 0, y = 0, w = 24, h = 10 },

                    datasource = req.datasourceUid is null ? null : new { type = "postgres", uid = req.datasourceUid },

                    targets = new object[]
                    {
                        new {
                            refId = "A",
                            format = panelType == "timeseries" ? "time_series" : "table",
                            rawSql = finalSql,
                            datasource = req.datasourceUid is null ? null : new { type = "postgres", uid = req.datasourceUid }
                        }
                    }
                }
            }
        },
        overwrite = true,
        message = "Created by Reports API"
    };

    using var http = new HttpClient { BaseAddress = new Uri(grafanaUrl) };
    http.DefaultRequestHeaders.Add("Authorization", $"Bearer {grafanaApiKey}");

    var resp = await http.PostAsJsonAsync("/api/dashboards/db", dashboardPayload);
    var content = await resp.Content.ReadAsStringAsync();

    if (!resp.IsSuccessStatusCode)
        return Results.Problem();

    return Results.Ok(content);
});

app.Run();