using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable
#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddCameraSiteCode : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "site_code",
                table: "cameras",
                type: "character varying(64)",
                maxLength: 64,
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_cameras_site_code",
                table: "cameras",
                column: "site_code",
                filter: "site_code IS NOT NULL");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_cameras_site_code",
                table: "cameras");

            migrationBuilder.DropColumn(
                name: "site_code",
                table: "cameras");
        }
    }
}
