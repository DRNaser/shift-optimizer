// =============================================================================
// SOLVEREIGN V4.1 - SendGrid Email Provider
// =============================================================================

using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Extensions.Options;
using Solvereign.Notify.Models;

namespace Solvereign.Notify.Providers;

/// <summary>
/// SendGrid email provider.
/// </summary>
public sealed partial class SendGridProvider : INotificationProvider
{
    private const string ApiUrl = "https://api.sendgrid.com/v3/mail/send";

    private readonly HttpClient _httpClient;
    private readonly SendGridConfig _config;
    private readonly ILogger<SendGridProvider> _logger;

    public string ProviderName => "SENDGRID";

    public SendGridProvider(
        HttpClient httpClient,
        IOptions<SendGridConfig> config,
        ILogger<SendGridProvider> logger)
    {
        _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        _config = config?.Value ?? throw new ArgumentNullException(nameof(config));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    public bool ValidateRecipient(string recipient)
    {
        if (string.IsNullOrWhiteSpace(recipient)) return false;
        return EmailRegex().IsMatch(recipient);
    }

    public async Task<SendResult> SendAsync(
        string recipient,
        string templateName,
        Dictionary<string, object> templateParams,
        string? portalUrl,
        CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(_config.ApiKey) || string.IsNullOrEmpty(_config.FromEmail))
        {
            return SendResult.PermanentError(ErrorCodes.ProviderAuthError, "SendGrid not configured");
        }

        if (!ValidateRecipient(recipient))
        {
            return SendResult.PermanentError(ErrorCodes.ProviderInvalidRecipient);
        }

        // Render email content
        var (subject, bodyText, bodyHtml) = RenderEmailContent(templateName, templateParams, portalUrl);

        var payload = new
        {
            personalizations = new[]
            {
                new
                {
                    to = new[] { new { email = recipient } },
                    subject
                }
            },
            from = new
            {
                email = _config.FromEmail,
                name = _config.FromName
            },
            content = new[]
            {
                new { type = "text/plain", value = bodyText },
                new { type = "text/html", value = bodyHtml }
            },
            tracking_settings = new
            {
                click_tracking = new { enable = true },
                open_tracking = new { enable = true }
            },
            custom_args = new
            {
                template_name = templateName
            }
        };

        var request = new HttpRequestMessage(HttpMethod.Post, ApiUrl)
        {
            Content = new StringContent(
                JsonSerializer.Serialize(payload),
                Encoding.UTF8,
                "application/json")
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _config.ApiKey);

        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(_config.TimeoutSeconds));

            var response = await _httpClient.SendAsync(request, cts.Token);

            if (response.StatusCode is HttpStatusCode.OK or HttpStatusCode.Accepted)
            {
                var messageId = response.Headers.GetValues("X-Message-Id").FirstOrDefault() ?? Guid.NewGuid().ToString();

                _logger.LogDebug(
                    "Email sent. MessageId: {MessageId}, Template: {Template}",
                    messageId, templateName);

                return SendResult.Ok(messageId, "ACCEPTED");
            }

            var responseBody = await response.Content.ReadAsStringAsync(cts.Token);
            var errorMessage = TryParseError(responseBody);

            _logger.LogWarning(
                "SendGrid send failed. StatusCode: {StatusCode}, Error: {Error}",
                response.StatusCode, errorMessage);

            return response.StatusCode switch
            {
                HttpStatusCode.TooManyRequests => SendResult.TransientError(
                    ErrorCodes.Provider429,
                    errorMessage,
                    GetRetryAfter(response)),

                HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden =>
                    SendResult.PermanentError(ErrorCodes.ProviderAuthError, errorMessage),

                HttpStatusCode.BadRequest when errorMessage.Contains("invalid", StringComparison.OrdinalIgnoreCase) =>
                    SendResult.PermanentError(ErrorCodes.ProviderInvalidRecipient, errorMessage),

                >= HttpStatusCode.InternalServerError =>
                    SendResult.TransientError(ErrorCodes.Provider5xx, errorMessage),

                _ => SendResult.TransientError(ErrorCodes.NetworkError, errorMessage)
            };
        }
        catch (TaskCanceledException) when (ct.IsCancellationRequested)
        {
            throw;
        }
        catch (TaskCanceledException)
        {
            _logger.LogWarning("SendGrid request timed out");
            return SendResult.TransientError(ErrorCodes.ProviderTimeout);
        }
        catch (HttpRequestException ex)
        {
            _logger.LogError(ex, "SendGrid request failed");
            return SendResult.TransientError(ErrorCodes.NetworkError);
        }
    }

    public async Task<bool> IsHealthyAsync(CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(_config.ApiKey))
            return false;

        try
        {
            var request = new HttpRequestMessage(HttpMethod.Get, "https://api.sendgrid.com/v3/scopes");
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _config.ApiKey);

            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(10));

            var response = await _httpClient.SendAsync(request, cts.Token);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    private static (string subject, string bodyText, string bodyHtml) RenderEmailContent(
        string templateName,
        Dictionary<string, object> templateParams,
        string? portalUrl)
    {
        var driverName = templateParams.GetValueOrDefault("driver_name", "").ToString() ?? "";
        var weekStart = templateParams.GetValueOrDefault("week_start", "").ToString() ?? "";

        string subject;
        string bodyText;
        string bodyHtml;

        switch (templateName.ToUpperInvariant())
        {
            case "PORTAL_INVITE":
                subject = "SOLVEREIGN - Ihr Schichtplan ist verfügbar";
                bodyText = $"""
                    Hallo {driverName},

                    Ihr neuer Schichtplan für die Woche {weekStart} ist verfügbar.

                    Bitte bestätigen Sie Ihren Plan hier: {portalUrl}

                    Mit freundlichen Grüßen,
                    Ihr Dispositionsteam
                    """;
                bodyHtml = $"""
                    <html>
                    <body style="font-family: Arial, sans-serif;">
                    <h2>Ihr Schichtplan ist verfügbar</h2>
                    <p>Hallo {driverName},</p>
                    <p>Ihr neuer Schichtplan für die Woche {weekStart} ist verfügbar.</p>
                    <p><a href="{portalUrl}" style="background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Schichtplan anzeigen</a></p>
                    <p>Mit freundlichen Grüßen,<br/>Ihr Dispositionsteam</p>
                    </body>
                    </html>
                    """;
                break;

            case "REMINDER_24H":
                subject = "SOLVEREIGN - Erinnerung: Schichtplan bestätigen";
                bodyText = $"""
                    Hallo {driverName},

                    Ihr Schichtplan wartet noch auf Ihre Bestätigung.

                    Bitte bestätigen Sie hier: {portalUrl}

                    Mit freundlichen Grüßen,
                    Ihr Dispositionsteam
                    """;
                bodyHtml = $"""
                    <html>
                    <body style="font-family: Arial, sans-serif;">
                    <h2>Erinnerung: Schichtplan bestätigen</h2>
                    <p>Hallo {driverName},</p>
                    <p>Ihr Schichtplan wartet noch auf Ihre Bestätigung.</p>
                    <p><a href="{portalUrl}" style="background-color: #ffc107; color: black; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Jetzt bestätigen</a></p>
                    <p>Mit freundlichen Grüßen,<br/>Ihr Dispositionsteam</p>
                    </body>
                    </html>
                    """;
                break;

            default:
                subject = "SOLVEREIGN - Benachrichtigung";
                bodyText = $"Hallo {driverName},\n\nLink: {portalUrl}";
                bodyHtml = $"<p>Hallo {driverName},</p><p><a href=\"{portalUrl}\">Link</a></p>";
                break;
        }

        return (subject, bodyText, bodyHtml);
    }

    private static string TryParseError(string body)
    {
        try
        {
            var doc = JsonDocument.Parse(body);
            if (doc.RootElement.TryGetProperty("errors", out var errors) && errors.GetArrayLength() > 0)
            {
                return errors[0].GetProperty("message").GetString() ?? "Unknown error";
            }
        }
        catch { }
        return "Unknown error";
    }

    private static TimeSpan? GetRetryAfter(HttpResponseMessage response)
    {
        if (response.Headers.RetryAfter?.Delta is { } delta)
            return delta;
        return TimeSpan.FromMinutes(1);
    }

    [GeneratedRegex(@"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")]
    private static partial Regex EmailRegex();
}
