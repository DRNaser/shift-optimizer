// =============================================================================
// SOLVEREIGN V4.1 - Notification Worker Entry Point
// =============================================================================

using Serilog;
using Solvereign.Notify.Api;
using Solvereign.Notify.Models;
using Solvereign.Notify.Providers;
using Solvereign.Notify.Repository;
using Solvereign.Notify.Worker;

Log.Logger = new LoggerConfiguration()
    .WriteTo.Console(
        outputTemplate: "[{Timestamp:HH:mm:ss} {Level:u3}] {Message:lj} {Properties:j}{NewLine}{Exception}")
    .Enrich.FromLogContext()
    .CreateLogger();

try
{
    Log.Information("Starting SOLVEREIGN Notification Worker");

    var builder = WebApplication.CreateBuilder(args);

    // Add Serilog
    builder.Host.UseSerilog();

    // Configuration
    builder.Services.Configure<NotifyWorkerConfig>(
        builder.Configuration.GetSection(NotifyWorkerConfig.SectionName));
    builder.Services.Configure<WhatsAppConfig>(
        builder.Configuration.GetSection(WhatsAppConfig.SectionName));
    builder.Services.Configure<SendGridConfig>(
        builder.Configuration.GetSection(SendGridConfig.SectionName));

    // Database connection
    var connectionString = builder.Configuration.GetConnectionString("Postgres")
        ?? throw new InvalidOperationException("Connection string 'Postgres' not configured");

    // Repository
    builder.Services.AddSingleton<INotifyRepository>(sp =>
        new NotifyRepository(connectionString, sp.GetRequiredService<ILogger<NotifyRepository>>()));

    // HTTP clients for providers
    builder.Services.AddHttpClient<WhatsAppProvider>();
    builder.Services.AddHttpClient<SendGridProvider>();

    // Register providers
    builder.Services.AddSingleton<WhatsAppProvider>();
    builder.Services.AddSingleton<SendGridProvider>();

    // Background worker
    builder.Services.AddHostedService<NotifyWorker>();

    // API controllers
    builder.Services.AddControllers();
    builder.Services.AddEndpointsApiExplorer();
    builder.Services.AddSwaggerGen(c =>
    {
        c.SwaggerDoc("v1", new() { Title = "SOLVEREIGN Notify API", Version = "v4.1" });
    });

    // Health checks
    builder.Services.AddHealthChecks()
        .AddNpgSql(connectionString, name: "postgres");

    var app = builder.Build();

    // Development only
    if (app.Environment.IsDevelopment())
    {
        app.UseSwagger();
        app.UseSwaggerUI();
    }

    // Health check endpoint
    app.MapHealthChecks("/health");

    // API routes
    app.MapControllers();

    // Minimal health endpoint
    app.MapGet("/", () => new
    {
        name = "SOLVEREIGN Notification Worker",
        version = "v4.1.0",
        status = "running"
    });

    await app.RunAsync();
}
catch (Exception ex)
{
    Log.Fatal(ex, "Application terminated unexpectedly");
    throw;
}
finally
{
    Log.CloseAndFlush();
}
